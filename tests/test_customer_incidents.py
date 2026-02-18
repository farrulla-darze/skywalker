"""Test script to verify customer_data agent with get_active_incidents tool.

This script sends a query to the chat API specifically designed to trigger the
customer_data agent to use the get_active_incidents tool.

Usage:
    poetry run python tests/test_customer_incidents.py
"""

import json
import httpx

def test_customer_incidents():
    """Test customer_data agent by asking about customer incidents."""

    # Use a customer email from the database
    customer_email = "joao.silva@email.com"
    user_id = "test-incidents-user"

    # Craft question to trigger customer_data agent with incidents
    question = f"Are there any active platform incidents or service issues affecting customer {customer_email}?"

    chat_url = "http://localhost:8000/chat"
    payload = {
        "userId": user_id,
        "question": question,
    }

    print("="*80)
    print("CUSTOMER DATA AGENT TEST - ACTIVE INCIDENTS")
    print("="*80)
    print(f"\nUser ID: {user_id}")
    print(f"Customer Email: {customer_email}")
    print(f"Question: {question}\n")
    print("-"*80)
    print("Sending request to /chat endpoint...")
    print("-"*80)

    try:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(chat_url, json=payload)
            response.raise_for_status()

            result = response.json()

            print("\n✅ RESPONSE RECEIVED\n")
            print("="*80)
            print("Response:")
            print("="*80)
            print(result.get("response", "No response"))
            print("\n" + "="*80)
            print("Metadata:")
            print("="*80)
            print(json.dumps(result.get("metadata", {}), indent=2))

            session_id = result.get("sessionId")
            if session_id:
                print("\n" + "="*80)
                print(f"Session ID: {session_id}")
                print("="*80)
                print("\nTo inspect conversation:")
                print(f"cat ~/.skywalker/sessions/{session_id}/conversations/main.jsonl | jq -s '.'")
                print(f"\nTo check customer_data agent conversation:")
                print(f"cat ~/.skywalker/sessions/{session_id}/conversations/customer_data.jsonl | jq -s '.'")

            return result

    except httpx.HTTPStatusError as e:
        print(f"\n❌ HTTP Error: {e}")
        print(f"Status Code: {e.response.status_code}")
        print(f"Response: {e.response.text}")
        raise
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise

if __name__ == "__main__":
    test_customer_incidents()
