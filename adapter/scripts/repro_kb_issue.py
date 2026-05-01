
import asyncio
import httpx
import json

async def test_reproduction():
    # Simulate a knowledge.document.added event
    # Based on the user's report, we suspect the KB mapping is not being created.
    
    # We'll use a mock payload that mimics what Open WebUI might send
    # when a document is added to a knowledge base.
    
    payload = {
        "event": "knowledge.document.added",
        "knowledge": {
            "id": "KB_0",
            "name": "My Knowledge Base"
        },
        "file": {
            "id": "f-123",
            "filename": "cloud_computing.pdf"
        }
    }
    
    # Send it to the adapter (assuming it's running on localhost:8002)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post("http://localhost:8002/api/v1/events", json=payload)
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.json()}")
            
            # Check mappings
            resp = await client.get("http://localhost:8002/internal/mappings/knowledge-bases")
            print(f"KB Mappings: {resp.json()}")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_reproduction())
