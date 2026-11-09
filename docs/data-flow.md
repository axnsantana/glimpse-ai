# Data flow

```text
User asks a question
   |
   v
Framework adapter (NiceGUI)    walks this client's element tree, and probes the browser
   |                           for grid filters, chart zoom and hidden series
   v
PageContext                    a framework-neutral snapshot, built at the moment of asking
   |
   v
Context builder                drops fields not on screen, runs your redact hook, computes
   |                           statistics, and fits everything into the token budget
   v
Engine                         direct, council, ADK, offline or your own, given messages and the snapshot
   |
   v
Model provider                 only if the engine calls one
   |
   v
Sanitizer                      on the server, for every chunk: no HTML, images or unsafe links
   |
   v
Panel                          in a Shadow DOM, building DOM nodes with textContent only
```

## Where page data goes

| Engine | Where page data goes |
|---|---|
| `offline` | Nowhere. It stays in your process |
| `direct` with `anthropic:` | Anthropic's API |
| `direct` with `vertex:` | Google Cloud Vertex AI, in the project and location you set |
| `direct` with `gemini:` | Google's Gemini API |
| `direct` with `openai:` | OpenAI's API |
| `direct` with `ollama:` or a `base_url` | That server |
| `council` | The same place as `direct` with its model strings. Each role may use a different model |
| `adk` or your ADK agent | Wherever the agent's models and tools send it. Your own tools receive the arguments the model gives them |
| Your own engine | Wherever your code sends it |

Glimpse itself has no telemetry and no hosted service.

## What is sent for each question

- **System prompt:** static instructions, with no page data in it
- **Tool definitions:** four read-only tools
- **History:** earlier questions and answers as text, newest first until the budget runs out
- **The latest user message:** the developer context and page state, fenced as data, then the question

The page state goes only in the latest message. Earlier messages keep only the question, so history stays small and the model always answers from the current screen.

## What runs where

| Step | Where |
|---|---|
| Tree walk | The event loop. It is quick, because it only references the data |
| Browser probe | The browser. It returns row indices and state rather than row data, with a 1 second timeout |
| Projection, filtering, sorting, statistics, redaction | A worker thread, so one large table cannot freeze other users |
| Tools | A worker thread |
| Plain sync engines | A worker thread |

## Conversation lifetime

A conversation lives on the NiceGUI client, which means one page load in one tab. A reload or a navigation to another page starts a new conversation. Nothing is written to disk. Closing the tab cancels any answer in progress.

## Swapping the serializer

`serializer=` takes a function `(page, detail) -> str`, and `glimpse.json_serializer` is included as an alternative to the default plain text. The builder calls it with less and less detail until the result fits the budget.
