# backend/services/ingest_service.py

import logging
import uuid
import json
from datetime import datetime
from sqlmodel import Session
from meilisearch import Client as MeiliClient
from .storage_service import save_media
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from db_setup import Run, Message, Call, Contact, Media, AleappArtifact, AleappReport

# Import embeddings service
from ai.embeddings import EmbeddingsService

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class IngestService:
    def ingest_to_all(
        self, parsed_data: dict, session: Session, meili_client: MeiliClient
    ) -> dict:
        """
        Full ingestion flow:
        1. Insert Run into DB
        2. Insert normalized data (messages, calls, etc.)
        3. Index relevant data in Meilisearch
        4. Save media to MinIO (via storage_services)
        """
        run_id = None
        try:
            # Create a new Run entry. The route must bind this to the
            # authenticated caller; no first-user/random-UUID fallback is allowed.
            raw_user_id = parsed_data.get("user_id")
            if not raw_user_id:
                raise ValueError("parsed_data.user_id is required for ingestion")
            try:
                user_id = uuid.UUID(str(raw_user_id))
            except (TypeError, ValueError) as e:
                raise ValueError(f"invalid ingestion user_id: {raw_user_id!r}") from e

            # Prepare metadata from UFDR extraction
            metadata = {}
            if "_extraction_info" in parsed_data:
                metadata["extraction_info"] = parsed_data["_extraction_info"]
            if "aleapp_data" in parsed_data:
                metadata["aleapp_summary"] = {
                    "output_directory": parsed_data["aleapp_data"].get(
                        "output_directory"
                    ),
                    "artifact_count": len(
                        parsed_data["aleapp_data"].get("artifacts", [])
                    ),
                    "report_count": len(parsed_data["aleapp_data"].get("reports", [])),
                    "timeline_count": len(
                        parsed_data["aleapp_data"].get("timeline", [])
                    ),
                }

            # Get file hash for deduplication
            file_content_hash = None
            original_file_path = None
            if "file_path" in parsed_data:
                original_file_path = parsed_data["file_path"]
                from ingest.services.cache_service import cache_service

                try:
                    file_content_hash = cache_service.get_file_hash_with_cache(
                        original_file_path
                    )
                    logger.info(f"Calculated file hash: {file_content_hash[:12]}...")
                except Exception as e:
                    logger.exception("Could not calculate file hash")
                    raise RuntimeError(
                        f"could not calculate file hash for {original_file_path}"
                    ) from e

            run = Run(
                ufdr_file_name=parsed_data.get("filename"),
                status="ingesting",
                start_time=datetime.utcnow(),
                user_id=user_id,
                extraction_metadata=json.dumps(metadata) if metadata else None,
                file_content_hash=file_content_hash,
                original_file_path=original_file_path,
            )
            session.add(run)
            session.flush()
            session.refresh(run)
            run_id = run.id

            # --- Ingest to Postgres ---
            # 2. Ingest Messages
            messages_to_ingest = [
                Message(
                    run_id=run_id,
                    sender=msg.get("sender"),
                    receiver=msg.get("receiver"),
                    timestamp=msg.get("timestamp"),
                    content=msg.get("content"),
                )
                for msg in parsed_data.get("messages", [])
            ]
            session.add_all(messages_to_ingest)

            # 3. Ingest Calls
            calls_to_ingest = [
                Call(
                    run_id=run_id,
                    caller=call.get("caller"),
                    receiver=call.get("receiver"),
                    timestamp=call.get("timestamp"),
                    duration=call.get("duration"),
                )
                for call in parsed_data.get("calls", [])
            ]
            session.add_all(calls_to_ingest)

            # 4. Ingest Contacts
            contacts_to_ingest = [
                Contact(
                    run_id=run_id,
                    name=contact.get("name"),
                    number=contact.get("number"),
                )
                for contact in parsed_data.get("contacts", [])
            ]
            session.add_all(contacts_to_ingest)

            session.flush()

            # --- Ingest to Meilisearch ---
            # 5. Indexing Messages for search
            meili_messages = [
                {
                    "id": str(uuid.uuid4()),  # Meili needs a unique string ID
                    "run_id": str(run_id),
                    "content": msg.get("content"),
                    "sender": msg.get("sender"),
                    "timestamp": msg.get("timestamp"),
                }
                for msg in parsed_data.get("messages", [])
            ]
            if meili_messages:
                meili_client.index("messages").add_documents(meili_messages)

            # --- Generate Embeddings for Semantic Search ---
            # 5b. Create embeddings for messages (enables semantic search)
            logger.info(
                f"Generating embeddings for {len(parsed_data.get('messages', []))} messages..."
            )
            try:
                embeddings_service = EmbeddingsService()

                # Prepare texts and metadata for embedding
                message_texts = []
                message_metadata = []

                for i, msg in enumerate(parsed_data.get("messages", [])):
                    # Create rich text representation for better semantic search
                    content = msg.get("content", "")
                    sender = msg.get("sender", "unknown")
                    receiver = msg.get("receiver", "unknown")

                    # Text to embed (include context)
                    text_to_embed = f"From {sender} to {receiver}: {content}"
                    message_texts.append(text_to_embed)

                    # Metadata to store with embedding
                    message_metadata.append(
                        {
                            "id": str(messages_to_ingest[i].id)
                            if i < len(messages_to_ingest)
                            else str(uuid.uuid4()),
                            "type": "message",
                            "sender": sender,
                            "receiver": receiver,
                            "content": content[:200],  # Preview only
                            "content_preview": content[:100] + "..."
                            if len(content) > 100
                            else content,
                            "timestamp": str(msg.get("timestamp", "")),
                            "run_id": str(run_id),
                        }
                    )

                # Generate and store embeddings
                if message_texts:
                    embeddings_service.create_index(
                        run_id=str(run_id),
                        texts=message_texts,
                        metadata=message_metadata,
                    )
                    logger.info(
                        f"Successfully created embeddings index for run {run_id}"
                    )
                else:
                    logger.info("No messages to embed")

            except Exception as e:
                logger.exception("Failed to generate embeddings")
                raise RuntimeError(
                    f"failed to generate embeddings for run {run_id}"
                ) from e

            # --- Save Media to MinIO (via storage service) ---
            # 6. Save media files and get paths
            media_paths = []
            for media_item in parsed_data.get("media", []):
                file_path = media_item.get("file_path")
                if file_path:
                    stored_path = save_media(file_path, str(run_id))
                    media_paths.append(
                        Media(
                            run_id=run_id,
                            original_path=file_path,
                            storage_path=stored_path,
                            media_type=media_item.get("type"),
                        )
                    )
            if media_paths:
                session.add_all(media_paths)

            # --- Save ALEAPP data to database ---
            # 7. Process ALEAPP artifacts and reports
            aleapp_data = parsed_data.get("aleapp_data")
            if aleapp_data:
                # Save ALEAPP artifacts
                aleapp_artifacts = []
                for artifact in aleapp_data.get("artifacts", []):
                    aleapp_artifact = AleappArtifact(
                        run_id=run_id,
                        artifact_type=artifact.get("type"),
                        filename=artifact.get("filename"),
                        file_path=artifact.get("path"),
                        category=artifact.get("category"),
                        row_count=artifact.get("row_count"),
                        data=json.dumps(
                            artifact.get("sample_data") or artifact.get("data")
                        )
                        if artifact.get("sample_data") or artifact.get("data")
                        else None,
                    )
                    aleapp_artifacts.append(aleapp_artifact)

                if aleapp_artifacts:
                    session.add_all(aleapp_artifacts)

                # Save ALEAPP reports
                aleapp_reports = []
                for report in aleapp_data.get("reports", []):
                    aleapp_report = AleappReport(
                        run_id=run_id,
                        report_type=report.get("type"),
                        filename=report.get("filename"),
                        file_path=report.get("path"),
                    )
                    aleapp_reports.append(aleapp_report)

                if aleapp_reports:
                    session.add_all(aleapp_reports)

                logger.info(
                    f"Saved {len(aleapp_artifacts)} ALEAPP artifacts and {len(aleapp_reports)} reports to database"
                )

            # --- Update Run status ---
            run.status = "complete"
            run.end_time = datetime.utcnow()
            session.add(run)
            session.commit()

            logger.info(f"Ingestion complete for run {run_id}")

            return {
                "run_id": str(run_id),
                "status": "complete",
            }

        except Exception as e:
            session.rollback()
            logger.error(f"Ingestion failed for run {run_id}: {e}")
            raise e
