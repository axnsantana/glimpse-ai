# Examples

These examples are how Glimpse is specified and tested: `tests/test_examples.py` runs each one as it ships, so what you read here works. Every file starts with what to try.

```bash
pip install -e ".[dev]"
python examples/01_quickstart.py
```

No API key is needed. Without one, the panel runs in offline demo mode and says so. It answers from simple rules, so it shows what Glimpse can see but not how well a model reasons. Set `ANTHROPIC_API_KEY` for real answers.

| Example | What it shows | Try this |
|---|---|---|
| [01_quickstart.py](01_quickstart.py) | One line adds an assistant to a page | Ask for the highest month, change the region, ask again |
| [02_sales_dashboard.py](02_sales_dashboard.py) | A full dashboard, read with no annotations | Filter the Orders grid, zoom the chart, hide a series, and ask about them |
| [03_large_data.py](03_large_data.py) | 200,000 points inside a 6,000-token budget | Ask for the trend, then open "What the assistant saw" |
| [04_multi_page.py](04_multi_page.py) | One call covers a multi-page app and sub pages | Move between pages and ask what is on each |
| [05_existing_layout.py](05_existing_layout.py) | Sharing a page with drawers and hostile CSS | Open the panel and watch the right drawer move over |
| [06_custom_engine.py](06_custom_engine.py) | Your own agent, in three forms | Visit `/`, `/protocol` and `/adapter` |
| [07_choose_your_model.py](07_choose_your_model.py) | Cloud or local models, prompts, usage and limits | Run with `GLIMPSE_MODEL=ollama:llama3.2` |
| [08_privacy_and_security.py](08_privacy_and_security.py) | Secrets stay out, attacks stay inert | Inspect `/`, then run the attack at `/red-team` |
| [09_developer_context.py](09_developer_context.py) | Adding what the screen cannot show | Flip the switch and ask about the notes |
| [10_two_users.py](10_two_users.py) | Two users on one server stay separate | Open `?user=ana` and `?user=ben` side by side |

## Why this is useful

Passing data to a chat function by hand works for one chart. It gets harder once users can filter, sort, zoom and switch tabs, because then you have to keep the assistant in sync with every control.

Example 02 has a grid filter that exists only in the browser. Python does not know about it, so a hand-wired assistant would answer from all 240 rows while the user looks at 8. Glimpse reads the filter when the question is asked, and it answers from the same 8 rows.
