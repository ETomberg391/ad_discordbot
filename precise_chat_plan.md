# Plan to Implement `/precise_answers`

This document outlines the plan to implement a new `/precise_answers` command for the Discord bot. This feature will allow users to toggle a mode where the bot provides more direct, "to-the-point" answers by parsing specially formatted output from the LLM.

## 1. Create a new module `precise_chat_module.py`

A new module will be created to contain the core logic for the "precise answers" feature.

-   **File:** `modules/precise_chat_module.py`
-   **Purpose:** This module will be responsible for generating the precisely formatted answer.
-   **Key Function:** A function named `get_precise_answer` will be the main entry point for this module.
    -   It will accept the user's prompt and the current `state` dictionary.
    -   It will inject a system prompt into the context to instruct the LLM to formulate a response, use `<thinking>` tags for internal thoughts, and wrap the final reply in `<chatting>` tags.
    -   It will make a single call to the `custom_chatbot_wrapper` to get the raw response from the LLM.
    -   It will parse the LLM's response by first ignoring any text before the last `</think>` or `</thinking>` tag, and then extracting the content from the last `<chatting>...</chatting>` block.
    -   It will implement a retry mechanism (up to 4 attempts) if the tags are not found in the response. If it fails after all retries, it will return a fallback message.

## 2. Modify `bot.py` to add the `/precise_answers` command

The main bot file will be updated to include the new user-facing command.

-   **File:** `bot.py`
-   **New Command:** A new hybrid command, `/precise_answers`, will be registered.
-   **Functionality:** This command will act as a toggle (on/off) for the precise answers mode.
-   **State Management:** The state of the toggle will be stored in the `bot_database`. A new dictionary will be added to the database to map a user or channel ID to a boolean value indicating if the mode is active.

## 3. Integrate the Precise Chat Module into the Response Flow

The existing message processing logic will be adapted to incorporate the new module.

-   **File:** `bot.py`
-   **Integration Point:** The `TaskProcessing` class, likely within the `message_llm_task` method, is the ideal place for this integration.
-   **Logic:**
    -   Before generating a response, the code will check the `bot_database` to see if the "precise answers" toggle is enabled for the current user/channel.
    -   If enabled, it will call `get_precise_answer` from `precise_chat_module.py` instead of the standard text generation flow.
    -   The result from `get_precise_answer` will then be sent back to the user.

## 4. Detailed Logic for `precise_chat_module.py`

Here is a more detailed look at the simplified implementation of the `get_precise_answer` function:

```python
# ad_discordbot/modules/precise_chat_module.py

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

        # Use the same async execution pattern as the original creative pass
        llm_func = partial(custom_chatbot_wrapper, text=text, state=state_copy, **kwargs)
        llm_generator = generate_in_executor(llm_func)

        full_response = ""
        async for response_chunk in llm_generator:
            if response_chunk.get('internal') and isinstance(response_chunk['internal'], list) and len(response_chunk['internal']) > 0:
                full_response = response_chunk['internal'][-1][1]

        attempts_list.append({"raw_output": full_response})

        # --- PARSING ---
        processed_response = full_response

        # 1. Ignore anything before the last </think> tag
        last_think_pos = processed_response.rfind('</think>')
        if last_think_pos != -1:
            processed_response = processed_response[last_think_pos + len('</think>'):]

        # 2. Ignore anything before the last </thinking> tag
        last_thinking_pos = processed_response.rfind('</thinking>')
        if last_thinking_pos != -1:
            processed_response = processed_response[last_thinking_pos + len('</thinking>'):]

        # 3. Find the last <chatting>...</chatting> block
        last_chat_pos = processed_response.rfind('<chatting>')
        if last_chat_pos != -1:
            substring = processed_response[last_chat_pos + len('<chatting>'):]
            end_chat_pos = substring.find('</chatting>')
            if end_chat_pos != -1:
                final_answer = substring[:end_chat_pos].strip()
                log_precise_entry(text, attempts_list, final_answer, f"from attempt {attempt + 1}")
                return final_answer

        # If no match, wait before retrying
        if attempt < max_retries - 1:
            await asyncio.sleep(1)

    # Fallback if all retries fail
    final_fallback_response = "I am sorry, I am having trouble formulating a response."
    log_precise_entry(text, attempts_list, final_fallback_response, f"fallback after {max_retries} retries")
    return final_fallback_response
```

## 5. Mermaid Diagram of the Plan

The following diagram illustrates the proposed architecture and flow:

```mermaid
graph TD
    A[User sends message] --> B{/precise_answers enabled?};
    B -- No --> C[Normal response flow];
    B -- Yes --> D[Precise response flow];
    D --> E[message_llm_task calls get_precise_answer];
    E --> F[get_precise_answer adds system prompt to context];
    F --> G[get_precise_answer calls custom_chatbot_wrapper];
    G --> H{Parse LLM Response};
    H --> I{Find last </think> tag};
    I --> J{Find last </thinking> tag};
    J --> K{Find last <chatting> block};
    K -- Found --> L[Extract text from tags];
    K -- Not Found --> M{Retry up to 4 times};
    M -- Success --> L;
    M -- Failure --> O[Return fallback message];
    L --> P[Send response to user];
    O --> P;
    C --> P;

    Q[User uses /precise_answers command] --> R[Toggle state in bot_database];
```

This plan provides a clear path to implementing the desired functionality in a modular and maintainable way.