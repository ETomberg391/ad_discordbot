import re
import asyncio
from functools import partial
import copy
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
    parsing the response, and extracting the content from within the tags.
    Includes a retry mechanism and an enhanced system prompt.
    """
    # Set flag to skip HTML escaping in the core wrapper
    state['skip_html_escape'] = True

    # A more robust system prompt to enforce the desired output format.
    system_prompt = """Your thought process should be outside of the chatting tags. Your final response to the user should be in-character and enclosed within <chatting> and </chatting> tags.

Example:
USER: What is 2+2?
ASSISTANT: The user is asking a simple math question. I will answer it in character.
<chatting>An easy one! The answer is 4.</chatting>

Your final, user-facing response MUST be inside <chatting> tags."""
    
    # Safely get the original context and prepend the system prompt
    original_context = state.get('context', '')
    state['context'] = f"{system_prompt}\n\n{original_context}"

    max_retries = 3
    last_raw_output = ""
    cleaned_response = ""

    # Deepcopy the state to avoid polluting history across retries
    original_state = copy.deepcopy(state)

    for attempt in range(max_retries):
        # Use a fresh copy of the state for each attempt
        current_state = copy.deepcopy(original_state)

        full_response = ""
        # Correctly call the generator using generate_in_executor
        func = partial(custom_chatbot_wrapper, text=text, state=current_state, **kwargs)
        response_generator = generate_in_executor(func)
        
        # The generator yields the full history, so we just need the last one.
        async for response_chunk in response_generator:
            if response_chunk.get('internal') and isinstance(response_chunk['internal'], list) and len(response_chunk['internal']) > 0:
                full_response = response_chunk['internal'][-1][1]
        
        last_raw_output = full_response

        # 1. Ignore any thinking process before a </think> tag
        cleaned_response = full_response
        if '</think>' in cleaned_response:
            cleaned_response = cleaned_response.split('</think>', 1)[-1]

        # 2. Find the content of the LAST <chatting> tag.
        last_chat_pos = cleaned_response.rfind('<chatting>')
        if last_chat_pos != -1:
            # Get the substring from the last <chatting> tag to the end
            substring = cleaned_response[last_chat_pos + len('<chatting>'):]
            
            # Find the first closing tag in the substring
            end_chat_pos = substring.find('</chatting>')
            
            if end_chat_pos != -1:
                final_answer = substring[:end_chat_pos].strip()
            else:
                # If no closing tag, take the whole substring
                final_answer = substring.strip()

            log_precise_answer(text, last_raw_output, final_answer)
            return final_answer
        
        # If no match, wait a moment before retrying
        if attempt < max_retries - 1:
            await asyncio.sleep(1)

    # 3. If after all retries no tags are found, use the last full, cleaned response as a fallback.
    final_answer = cleaned_response.strip()
    log_precise_answer(text, last_raw_output, final_answer)
    return final_answer
