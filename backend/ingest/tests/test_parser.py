import unittest
from pathlib import Path
from services.parser_service import UFDRParser


class TestUFDRParser(unittest.TestCase):

    def setUp(self):
        # Paths to dummy files
        self.xml_file = Path("tests/dummy.ufdr.xml")
        self.json_file = Path("tests/dummy.ufdr.json")
        self.csv_file = Path("tests/dummy.ufdr.csv")

        # Create dummy XML file
        self.xml_file.write_text("""<?xml version="1.0"?>
<ufdr>
    <messages>
        <message>
            <from>Alice</from>
            <to>Bob</to>
            <content>Hello</content>
        </message>
    </messages>
</ufdr>
""", encoding="utf-8")

        # Create dummy JSON file
        self.json_file.write_text("""{
    "messages": [
        {"from": "Alice", "to": "Bob", "content": "Hello JSON"}
    ]
}""", encoding="utf-8")

        # Create dummy CSV file
        self.csv_file.write_text("""from,to,content
Alice,Bob,Hello CSV
""", encoding="utf-8")

    def tearDown(self):
        # Clean up dummy files
        self.xml_file.unlink()
        self.json_file.unlink()
        self.csv_file.unlink()

    def test_parse_xml(self):
        result = UFDRParser.parse_file(str(self.xml_file))
        self.assertIn("messages", result)
        self.assertIsInstance(result["messages"], list)

    def test_parse_json(self):
        result = UFDRParser.parse_file(str(self.json_file))
        self.assertIn("messages", result)
        self.assertIsInstance(result["messages"], list)

    def test_parse_csv(self):
        result = UFDRParser.parse_file(str(self.csv_file))
        self.assertIn("messages", result)
        self.assertIsInstance(result["messages"], list)


if __name__ == "__main__":
    unittest.main()
