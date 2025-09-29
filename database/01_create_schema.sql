-- SCHEMA CREATION
-- Table 1: Contacts (Primary Key: contact_id)
CREATE TABLE Contacts (
    contact_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone_number VARCHAR(20) UNIQUE NOT NULL, -- Ensures no duplicate numbers
    email VARCHAR(255),
    alias VARCHAR(255) -- Helpful for linking multiple names to a single contact
);

-- Table 2: Calls (Primary Keys: call_id, Foreign Keys: caller_id, receiver_id)
CREATE TABLE Calls (
    call_id SERIAL PRIMARY KEY,
    caller_id INT REFERENCES Contacts(contact_id),
    receiver_id INT REFERENCES Contacts(contact_id),
    call_type VARCHAR(50) NOT NULL, -- 'Incoming', 'Outgoing', 'Missed', 'VoIP'
    duration INT, -- Duration in seconds
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Table 3: Messages (Primary Keys: message_id, Foreign Keys: sender_id, receiver_id)
CREATE TABLE Messages (
    message_id SERIAL PRIMARY KEY,
    sender_id INT REFERENCES Contacts(contact_id),
    receiver_id INT REFERENCES Contacts(contact_id),
    content TEXT NOT NULL,
    app_type VARCHAR(50) NOT NULL, -- 'SMS', 'WhatsApp', 'Signal', 'Telegram'
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Table 4: Media (Primary Key: media_id)
CREATE TABLE Media (
    media_id SERIAL PRIMARY KEY,
    file_path VARCHAR(512) NOT NULL,
    file_hash VARCHAR(64) UNIQUE, -- Crucial for forensic validation (e.g., SHA256)
    media_type VARCHAR(50) NOT NULL, -- 'image', 'video', 'document'
    size_bytes BIGINT,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
);