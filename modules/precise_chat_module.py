import re
import asyncio
from functools import partial
from modules.utils_tgwui import custom_chatbot_wrapper
from modules.utils_asyncio import generate_in_executor
import os
from datetime import datetime

LOG_DIR = 'modules/precise_logs'
SESSION_LOG_FILE = None

def log_precise_answer(input_text, raw_output, final_answer):
    """Logs the input, raw output, and final answer to a single session log file."""
    global SESSION_LOG_FILE
    os.makedirs(LOG_DIR, exist_ok=True)

    if SESSION_LOG_FILE is None:
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        SESSION_LOG_FILE = os.path.join(LOG_DIR, f"{timestamp}_precise_session.log")

    log_content = (
        f"--- ENTRY @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')} ---\n"
        f"--- INPUT ---\n{input_text}\n\n"
        f"--- RAW LLM OUTPUT ---\n{raw_output}\n\n"
        f"--- FINAL ANSWER ---\n{final_answer}\n"
        f"--------------------------------------------------\n\n"
    )
    
    with open(SESSION_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_content)

async def get_precise_answer(text, state, **kwargs):
    """
    Generates a precise answer by instructing the LLM to use <chatting> tags,
    parsing the response, and extracting the content.
    Includes a retry mechanism and logging.
    """
    # Set flag to skip HTML escaping in the core wrapper
    state['skip_html_escape'] = True

    system_prompt = "You are a precise and factual assistant. You must carefully analyze the user's query and provide a direct, concise answer. Your final response must be enclosed within <chatting> and </chatting> tags. For example: <chatting>This is the direct answer.</chatting>"
    
    # Safely get the original context and prepend the system prompt
    original_context = state.get('context', '')
    state['context'] = f"{system_prompt}\n\n{original_context}"

    max_retries = 3
    last_raw_output = ""
    cleaned_response = ""

    for attempt in range(max_retries):
        full_response = ""
        # Correctly call the generator using generate_in_executor
        func = partial(custom_chatbot_wrapper, text=text, state=state, **kwargs)
        async for response_chunk in generate_in_executor(func):
            # Assuming the final, complete response is in the 'internal' key
            if response_chunk.get('internal') and isinstance(response_chunk['internal'], list) and len(response_chunk['internal']) > 0:
                # The response is often a list of lists, e.g., [['request', 'response']]
                full_response = response_chunk['internal'][-1][1]
        
        last_raw_output = full_response

        # 1. Ignore any thinking process before a </think> tag
        cleaned_response = full_response
        if '</think>' in cleaned_response:
            cleaned_response = cleaned_response.split('</think>', 1)[-1]

        # 2. Find the content of the last <chatting> tag.
        matches = re.findall(r'<chatting>(.*)', cleaned_response, re.DOTALL)

        # 3. If matches are found, process the last one.
        if matches:
            last_match = matches[-1]
            # If a closing tag exists in the match, extract content between the tags.
            if '</chatting>' in last_match:
                final_answer = last_match.split('</chatting>')[0].strip()
            else:
                # Otherwise, return the entire match.
                final_answer = last_match.strip()
            
            log_precise_answer(text, last_raw_output, final_answer)
            return final_answer
        
        # If no match, wait a moment before retrying
        if attempt < max_retries - 1:
            await asyncio.sleep(1) # Small delay before retrying

    # 4. If after all retries no tags are found, use the last full, cleaned response.
    final_answer = cleaned_response.strip()
    log_precise_answer(text, last_raw_output, final_answer)
    return final_answer
