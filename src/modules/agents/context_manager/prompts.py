from datetime import datetime


def construct_main_agent_system_prompt(session_id: str, user_id: str) -> str:
    return f"""
    You are a helpful assistant. Your task is to answer the user's question.
    
    Session ID: {session_id}
    User ID: {user_id}
    Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    """