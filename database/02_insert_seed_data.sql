INSERT INTO Contacts (name, phone_number, email, alias) VALUES
(
    'Ramesh Kumar (Target)', 
    '+919876543210', 
    'ramesh.k@fakemail.com', 
    'RK'
),  -- contact_id: 1 (Suspect A)
(
    'Ajay Sharma', 
    '+919911223344', 
    'ajay.s@fakemail.com', 
    'AS'
),      -- contact_id: 2 (Known Accomplice)
(
    'Mr. Ben Smith (INTL)', 
    '+442071234567', 
    'ben.s@offshoremail.co.uk', 
    'BS'
), -- contact_id: 3 (International Link)
(
    'Pooja Kumar (Wife)', 
    '+918000111222', 
    'pooja.k@fakemail.com', 
    'Wife'
),    -- contact_id: 4 (Family)
(
    'Local Courier Service', 
    '+917770001111', 
    NULL, 
    'Courier'
),       -- contact_id: 5
(
    'Unsaved No. A', 
    '+12125550100', 
    NULL, 
    NULL
),               -- contact_id: 6 (Unsaved US Number)
(
    'Bank Alert', 
    '56789', 
    NULL, 
    NULL
),                      -- contact_id: 7 (Short Code)
(
    'Suresh Trader', 
    '+919456000001', 
    'suresh.t@fakemail.com', 
    NULL
),    -- contact_id: 8
(
    'Neha Verma', 
    '+918889991111', 
    NULL, 
    'NV'
),                       -- contact_id: 9
(
    'Investigator John (Dummy)', 
    '+919000000000', 
    NULL, 
    NULL
); -- contact_id: 10 (Dummy for testing)

INSERT INTO Calls (caller_id, receiver_id, call_type, duration, timestamp) VALUES
(
    1, 
    2, 
    'Outgoing', 
    185, 
    '2025-09-28 10:05:00+05:30'
),  -- Suspect A to Accomplice (Long Call)
(
    3, 
    1, 
    'Incoming', 
    34, 
    '2025-09-28 11:30:00+05:30'
),  -- INTL Link to Suspect A
(
    1, 
    4, 
    'Outgoing', 
    450, 
    '2025-09-28 14:00:00+05:30'
), -- Suspect A to Wife (Long/Normal)
(
    1, 
    2, 
    'Missed', 
    0, 
    '2025-09-28 17:15:00+05:30'
),   -- Suspect A missed call to Accomplice
(
    2, 
    1, 
    'Incoming', 
    12, 
    '2025-09-28 17:16:00+05:30'
),  -- Accomplice calls Suspect A back (short)
(
    6, 
    1, 
    'Incoming', 
    210, 
    '2025-09-27 09:00:00+05:30'
),  -- Unsaved US to Suspect A
(
    1, 
    5, 
    'Outgoing', 
    55, 
    '2025-09-27 12:45:00+05:30'
),  -- Suspect A to Courier (Legitimate)
(
    4, 
    1, 
    'Incoming', 
    10, 
    '2025-09-26 20:00:00+05:30'
),  -- Wife to Suspect A (Short/Late)
(
    1, 
    3, 
    'Outgoing', 
    60, 
    '2025-09-26 15:30:00+05:30'
),  -- Suspect A to INTL Link
(
    8, 
    1, 
    'Incoming', 
    90, 
    '2025-09-25 11:00:00+05:30'
); -- Trader to Suspect A

INSERT INTO Messages (sender_id, receiver_id, content, app_type, timestamp) VALUES
(
    1, 
    2, 
    'Did you secure the package? Use the secondary location. Avoid the usual spot.', 
    'WhatsApp', 
    '2025-09-28 10:10:00+05:30'
), -- Suspect A to Accomplice (Incriminating)
(
    2, 
    1, 
    'Done. The drop is secure. Sent you the payment proof.', 
    'WhatsApp', 
    '2025-09-28 10:35:00+05:30'
), -- Accomplice to Suspect A
(
    3, 
    1, 
    'Transfer sent. BTC address: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa', 
    'Signal', 
    '2025-09-28 11:35:00+05:30'
), -- INTL Link to Suspect A (Key Evidence: Bitcoin Address)
(
    1, 
    4, 
    'Will be late, stuck in a meeting. Dinner at 9.', 
    'SMS', 
    '2025-09-28 18:00:00+05:30'
),   -- Suspect A to Wife (Legitimate)
(
    7, 
    1, 
    'ALERT: Withdrawal of INR 50,000 from A/C ****1234 on 28-09-2025. Call us if unauthorized.', 
    'SMS', 
    '2025-09-28 09:00:00+05:30'
),  -- Bank Alert (SMS Shortcode)
(
    1, 
    6, 
    'Got your message, but this is a secure line. Switch back to Telegram now.', 
    'WhatsApp', 
    '2025-09-27 09:15:00+05:30'
), -- Suspect A to Unsaved US No. (Security Concern)
(
    8, 
    1, 
    'Market rate for a unit is 4.5. Can deliver tomorrow morning. Confirm with cash on delivery.', 
    'WhatsApp', 
    '2025-09-26 15:00:00+05:30'
), -- Trader to Suspect A (Suspicious Content)
(
    1, 
    3, 
    'The "investment" is ready. Need the wallet details for the final push.', 
    'Signal', 
    '2025-09-26 15:40:00+05:30'
), -- Suspect A to INTL Link (Link to Bitcoin Address)
(
    9, 
    1, 
    'Are you coming to the event tomorrow? Everyone is asking for you.', 
    'WhatsApp', 
    '2025-09-25 19:30:00+05:30'
), -- Neha to Suspect A (Social)
(
    1, 
    10, 
    'This is a test message for our SIH database setup.', 
    'SMS', 
    '2025-09-29 10:30:00+05:30'
); -- Suspect A to Dummy

INSERT INTO Media (file_path, file_hash, media_type, size_bytes, timestamp) VALUES
(
    '/storage/emulated/0/DCIM/Camera/IMG_20250928_103700.jpg', 
    'h12a7732a90b4d44e5d6a2f074b1234567890abcdef1234567890ab', 
    'image', 
    1024567, 
    '2025-09-28 10:37:00+05:30'
), -- Standard Photo
(
    '/storage/emulated/0/Download/Invoice_001.pdf', 
    'h23b8843b0c5e55f6e7b3g085c234567890abcdef1234567890ac', 
    'document', 
    55000, 
    '2025-09-27 15:20:00+05:30'
), -- Normal Document
(
    '/storage/emulated/0/Documents/Hidden/Wallet_Screenshot.png', 
    'h34c9954c1d6f66g7f8c4h096d34567890abcdef1234567890ad', 
    'image', 
    345000, 
    '2025-09-26 11:00:00+05:30'
), -- Suspicious File
(
    '/storage/emulated/0/WhatsApp/Media/Video/VID-20250928-WA0001.mp4', 
    'h45d0065d2e7g77h8g9d5i107e4567890abcdef1234567890ae', 
    'video', 
    5600000, 
    '2025-09-28 14:00:00+05:30'
), -- WhatsApp Video
(
    '/storage/emulated/0/Signal/Media/Signal-IMG-1234.jpg', 
    'h56e1176e3f8h88i9h0e6j118f567890abcdef1234567890af', 
    'image', 
    150000, 
    '2025-09-28 15:00:00+05:30'
), -- Signal Image
(
    '/storage/emulated/0/Download/Map_Location_2.kml', 
    'h67f2287f4g9i99j0i1f7k129g67890abcdef1234567890ag', 
    'document', 
    12000, 
    '2025-09-27 10:00:00+05:30'
), -- Suspicious KML (Geographical) file
(
    '/storage/emulated/0/DCIM/Screenshots/SS-20250927-142010.jpg', 
    'h78g3398g5h0j00k1j2g8l130h7890abcdef1234567890ah', 
    'image', 
    210000, 
    '2025-09-27 14:20:10+05:30'
), -- Screenshot
(
    '/storage/emulated/0/WhatsApp/Media/Document/Final_Agreement.pdf', 
    'h89h4409h6i1k11l2k3h9m141i890abcdef1234567890ai', 
    'document', 
    45000, 
    '2025-09-26 18:00:00+05:30'
), -- Another Document
(
    '/storage/emulated/0/Android/data/com.app/cache/temp_file.dat', 
    'h90i5510i7j2l22m3l4i0n152j90abcdef1234567890aj', 
    'document', 
    500, 
    '2025-09-25 23:00:00+05:30'
), -- Small, hidden App File
(
    '/storage/emulated/0/Pictures/Holiday/Beach_Pic.jpg', 
    'h01j6621j8k3m33n4m5j1o163k01abcdef1234567890ak', 
    'image', 
    900000, 
    '2025-09-25 10:00:00+05:30'
); -- Normal photo