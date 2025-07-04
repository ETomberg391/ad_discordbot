import re
import asyncio
from functools import partial
import copy
from modules.utils_tgwui import custom_chatbot_wrapper
from modules.text_generation import generate_reply
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
    """Logs a complete interaction entry to the session log file, supporting two-pass architecture."""
    if not SESSION_LOG_FILE:
        return

    log_content = (
        f"--- ENTRY @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')} ---\n"
        f"--- INPUT ---\n{input_text}\n\n"
    )

    for i, attempt_data in enumerate(attempts_list):
        # Handle both old string-based attempts and new dict-based attempts for compatibility
        if isinstance(attempt_data, dict):
            pass1_out = attempt_data.get("pass1_creative_output", "N/A")
            pass2_out = attempt_data.get("pass2_refined_output", "N/A")
            log_content += (
                f"--- ATTEMPT {i + 1} ---\n"
                f"--- PASS 1 (Creative) RAW OUTPUT ---\n{pass1_out}\n\n"
                f"--- PASS 2 (Refiner) RAW OUTPUT ---\n{pass2_out}\n\n"
            )
        else:  # Fallback for old log format
            log_content += f"--- ATTEMPT {i + 1} RAW LLM OUTPUT ---\n{attempt_data}\n\n"

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
    Generates a precise answer using a two-pass refinement architecture.
    1. Creative Pass: Generates a rich, in-character response.
    2. Refiner Pass: Cleans and formats the response from Pass 1.
    """
    # Set flag to skip HTML escaping in the core wrapper
    state['skip_html_escape'] = True

    # --- PROMPTS ---
    refiner_prompt_template = """Transform the following text into a clean response. Remove all third-person descriptions and meta-commentary. Enclose the final, pure first-person response in <chatting> tags.

--- EXAMPLE ---
TEXT TO REFINE:
*He tilts his head.* I am well, thank you. How are you?

REFINED OUTPUT:
<chatting>I am well, thank you. How are you?</chatting>
--- END EXAMPLE ---

--- TASK ---
TEXT TO REFINE:
{pass1_raw_output}

REFINED OUTPUT:
"""

    max_retries = 3
    raw_attempts = []

    for attempt in range(max_retries):
        # --- PASS 1: CREATIVE ---
        # Use a deepcopy of the state to avoid polluting the main history.
        # No special creative_prompt is needed; the natural character context is sufficient.
        creative_state = copy.deepcopy(state)

        # Generate the initial, potentially messy response
        creative_func = partial(custom_chatbot_wrapper, text=text, state=creative_state, **kwargs)
        creative_generator = generate_in_executor(creative_func)
        pass1_raw_output = ""
        async for response_chunk in creative_generator:
            if response_chunk.get('internal') and isinstance(response_chunk['internal'], list) and len(response_chunk['internal']) > 0:
                pass1_raw_output = response_chunk['internal'][-1][1]

        # --- PASS 2: REFINER ---
        # Create the refiner state by copying the original state.
        # This ensures all necessary default values (like stopping_strings) are present.
        refiner_state = copy.deepcopy(state)
        refiner_state['stream'] = False  # We need the full response for parsing, so disable streaming

        # Construct the prompt for the refiner using the few-shot template
        refiner_prompt_text = refiner_prompt_template.format(pass1_raw_output=pass1_raw_output)

        # Use the low-level generate_reply for raw text completion
        # This is a synchronous generator, so we need to handle it accordingly
        pass2_refined_output = ""
        reply_generator = generate_reply(refiner_prompt_text, refiner_state, is_chat=False)
        for reply in reply_generator:
            pass2_refined_output = reply

        raw_attempts.append({
            "pass1_creative_output": pass1_raw_output,
            "pass2_refined_output": pass2_refined_output
        })

        # --- FINAL EXTRACTION ---
        # Use the simple "Last Block Extraction" on the refined output
        last_chat_pos = pass2_refined_output.rfind('<chatting>')
        if last_chat_pos != -1:
            substring = pass2_refined_output[last_chat_pos + len('<chatting>'):]
            end_chat_pos = substring.find('</chatting>')
            if end_chat_pos != -1:
                final_answer = substring[:end_chat_pos].strip()
                log_precise_entry(text, raw_attempts, final_answer, f"from attempt {attempt + 1}")
                return final_answer

        # If no match, wait a moment before retrying
        if attempt < max_retries - 1:
            await asyncio.sleep(1)

    # Fallback if all retries fail
    final_answer = "I am sorry, I am having trouble formulating a response."
    log_precise_entry(text, raw_attempts, final_answer, f"fallback after {max_retries} retries")
    return final_answer
