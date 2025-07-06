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

def _initialize_session_log():
    """(Internal) Creates a single log file for the bot's entire session."""
    global SESSION_LOG_FILE
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    SESSION_LOG_FILE = os.path.join(LOG_DIR, f"session_{timestamp}.log")

def log_precise_entry(input_text, attempts_list, final_answer, source):
    """Logs a complete interaction entry to the session log file."""
    if not SESSION_LOG_FILE:
        return

    log_content = (
        f"--- ENTRY @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')} ---\n"
        f"--- INPUT ---\n{input_text}\n\n"
    )

    for i, attempt_data in enumerate(attempts_list):
        raw_output = attempt_data.get("raw_output", "N/A")
        log_content += f"--- ATTEMPT {i + 1} RAW LLM OUTPUT ---\n{raw_output}\n\n"

    log_content += (
        f"--- FINAL ANSWER ({source}) ---\n{final_answer}\n"
        f"--------------------------------------------------\n\n"
    )

    with open(SESSION_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_content)

# Initialize the log file once, when this module is first imported.
_initialize_session_log()


async def get_precise_answer(text, state, **kwargs):
    """
    Generates a precise, in-character answer by making a single call to the LLM,
    instructing it to use <chatting> tags. Retries up to 4 times.
    """
    state['skip_html_escape'] = True

    system_prompt = (
        "You are an AI character. Your goal is to provide an in-character response. "
        "You can think to yourself using <thinking>...</thinking> tags, but this will be hidden from the user. "
        "Your final, user-visible response MUST be enclosed in a single <chatting>...</chatting> block. "
        "For example: <thinking>I should respond politely.</thinking><chatting>Hello there! How can I help you?</chatting>"
    )

    max_retries = 4
    attempts_list = []
    original_context = state.get('context', '')

    for attempt in range(max_retries):
        # Use a deepcopy of the state to avoid polluting the main history with system prompts.
        state_copy = copy.deepcopy(state)
        state_copy['context'] = f"{system_prompt}\n{original_context}"

        # Dynamically add '</chatting>' to the stopping strings to prevent the model from looping.
        stopping_strings = state_copy.get('stopping_strings', [])
        if '</chatting>' not in stopping_strings:
            stopping_strings.append('</chatting>')
        state_copy['stopping_strings'] = stopping_strings

        # Use the same async execution pattern as the original creative pass
        llm_func = partial(custom_chatbot_wrapper, text=text, state=state_copy, **kwargs)
        llm_generator = generate_in_executor(llm_func)

        full_response = ""
        async for response_chunk in llm_generator:
            if response_chunk.get('internal') and isinstance(response_chunk['internal'], list) and len(response_chunk['internal']) > 0:
                full_response = response_chunk['internal'][-1][1]

        # If we used '</chatting>' as a stop string, the model output will likely be missing it.
        # We add it back before parsing to ensure the block is complete.
        full_response += '</chatting>'

        attempts_list.append({"raw_output": full_response})

        # --- PARSING ---
        # Find the last occurrence of </chatting> and work backwards to find the start.
        # This is more robust than regex or multi-step parsing.
        end_chat_pos = full_response.rfind('</chatting>')
        if end_chat_pos != -1:
            start_chat_pos = full_response.rfind('<chatting>', 0, end_chat_pos)
            if start_chat_pos != -1:
                final_answer = full_response[start_chat_pos + len('<chatting>'):end_chat_pos].strip()
                log_precise_entry(text, attempts_list, final_answer, f"from attempt {attempt + 1}")
                return final_answer

        # If no match, wait before retrying
        if attempt < max_retries - 1:
            await asyncio.sleep(1)

    # Fallback if all retries fail
    final_fallback_response = "I am sorry, I am having trouble formulating a response."
    log_precise_entry(text, attempts_list, final_fallback_response, f"fallback after {max_retries} retries")
    return final_fallback_response
