-- Clean up empty Run entries and their associated queries
-- These are runs with no data (no messages, calls, contacts, or media)

-- First, let's see what we're deleting
SELECT 
    r.id,
    r.ufdr_file_name,
    r.status,
    COUNT(DISTINCT m.id) as message_count,
    COUNT(DISTINCT c.id) as call_count,
    COUNT(DISTINCT co.id) as contact_count,
    COUNT(DISTINCT me.id) as media_count
FROM run r
LEFT JOIN message m ON m.run_id = r.id
LEFT JOIN call c ON c.run_id = r.id
LEFT JOIN contact co ON co.run_id = r.id
LEFT JOIN media me ON me.run_id = r.id
GROUP BY r.id, r.ufdr_file_name, r.status
HAVING 
    COUNT(DISTINCT m.id) = 0 AND
    COUNT(DISTINCT c.id) = 0 AND
    COUNT(DISTINCT co.id) = 0 AND
    COUNT(DISTINCT me.id) = 0;

-- Now delete the queries associated with these empty runs
DELETE FROM query
WHERE run_id IN (
    SELECT r.id
    FROM run r
    LEFT JOIN message m ON m.run_id = r.id
    LEFT JOIN call c ON c.run_id = r.id
    LEFT JOIN contact co ON co.run_id = r.id
    LEFT JOIN media me ON me.run_id = r.id
    GROUP BY r.id
    HAVING 
        COUNT(DISTINCT m.id) = 0 AND
        COUNT(DISTINCT c.id) = 0 AND
        COUNT(DISTINCT co.id) = 0 AND
        COUNT(DISTINCT me.id) = 0
);

-- Delete the results associated with these empty runs
DELETE FROM result
WHERE run_id IN (
    SELECT r.id
    FROM run r
    LEFT JOIN message m ON m.run_id = r.id
    LEFT JOIN call c ON c.run_id = r.id
    LEFT JOIN contact co ON co.run_id = r.id
    LEFT JOIN media me ON me.run_id = r.id
    GROUP BY r.id
    HAVING 
        COUNT(DISTINCT m.id) = 0 AND
        COUNT(DISTINCT c.id) = 0 AND
        COUNT(DISTINCT co.id) = 0 AND
        COUNT(DISTINCT me.id) = 0
);

-- Delete the empty runs
DELETE FROM run
WHERE id IN (
    SELECT r.id
    FROM run r
    LEFT JOIN message m ON m.run_id = r.id
    LEFT JOIN call c ON c.run_id = r.id
    LEFT JOIN contact co ON co.run_id = r.id
    LEFT JOIN media me ON me.run_id = r.id
    GROUP BY r.id
    HAVING 
        COUNT(DISTINCT m.id) = 0 AND
        COUNT(DISTINCT c.id) = 0 AND
        COUNT(DISTINCT co.id) = 0 AND
        COUNT(DISTINCT me.id) = 0
);

-- Verify what's left
SELECT 
    r.id,
    r.ufdr_file_name,
    r.status,
    COUNT(DISTINCT m.id) as message_count,
    COUNT(DISTINCT c.id) as call_count,
    COUNT(DISTINCT co.id) as contact_count,
    COUNT(DISTINCT me.id) as media_count
FROM run r
LEFT JOIN message m ON m.run_id = r.id
LEFT JOIN call c ON c.run_id = r.id
LEFT JOIN contact co ON co.run_id = r.id
LEFT JOIN media me ON me.run_id = r.id
GROUP BY r.id, r.ufdr_file_name, r.status
ORDER BY r.start_time DESC;

