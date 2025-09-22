# backend/services/ingest_service.py

import logging
import uuid
from datetime import datetime
from sqlmodel import Session
from meilisearch_python_sdk import Client as MeiliClient
from .storage_services import save_media
from ingest.db_setup import Run, Message, Call, Contact, Media

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class IngestService:
    def ingest_to_all(
        self,
        parsed_data: dict,
        session: Session,
        meili_client: MeiliClient
    ) -> dict:
        """
        Full ingestion flow:
        1. Insert Run into DB
        2. Insert normalized data (messages, calls, etc.)
        3. Index relevant data in Meilisearch
        4. Save media to MinIO (via storage_services)
        """
        try:
            # Create a new Run entry
            run = Run(
                ufdr_file_name=parsed_data.get("filename"),
                status="ingesting",
                start_time=datetime.utcnow(),
                user_id=parsed_data.get("user_id", 1),
            )
            session.add(run)
            session.commit()
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
                ) for msg in parsed_data.get("messages", [])
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
                ) for call in parsed_data.get("calls", [])
            ]
            session.add_all(calls_to_ingest)

            # 4. Ingest Contacts
            contacts_to_ingest = [
                Contact(
                    run_id=run_id,
                    name=contact.get("name"),
                    number=contact.get("number"),
                ) for contact in parsed_data.get("contacts", [])
            ]
            session.add_all(contacts_to_ingest)

            session.commit()

            # --- Ingest to Meilisearch ---
            # 5. Indexing Messages for search
            meili_messages = [
                {
                    "id": str(uuid.uuid4()),  # Meili needs a unique string ID
                    "run_id": str(run_id),
                    "content": msg.get("content"),
                    "sender": msg.get("sender"),
                    "timestamp": msg.get("timestamp"),
                } for msg in parsed_data.get("messages", [])
            ]
            if meili_messages:
                meili_client.index("messages").add_documents(meili_messages)

            # --- Save Media to MinIO (via storage service) ---
            # 6. Save media files and get paths
            media_paths = []
            for media_item in parsed_data.get("media", []):
                file_path = media_item.get("file_path")
                if file_path:
                    stored_path = save_media(file_path, str(run_id))
                    media_paths.append(Media(
                        run_id=run_id,
                        original_path=file_path,
                        storage_path=stored_path,
                        media_type=media_item.get("type")
                    ))
            if media_paths:
                session.add_all(media_paths)
                session.commit()

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
