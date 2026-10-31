# ModelBump

**Dependabot for LLM models.** ModelBump finds the AI models your code depends on and warns you before a provider retires them. Later versions will also test the old model against its replacement, repair prompts that regress, and open the upgrade pull request for you.

!!! note "v0.5.0: scan, test the new model on your own prompts, and repair what regressed"
    The first stage, **Scan**, is out as a command-line tool and a GitHub Action:

    ```bash
    pip install modelbump
    modelbump scan .
    ```

    The second, **Test**, builds a regression suite from your app's own LLM calls and compares the old and the new model on it, with a calibrated judge for free text:

    ```bash
    modelbump suite . --generate 2 --output suite.json
    modelbump test suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none
    ```

    The third, **Repair**, proposes prompt fixes for the cases that regressed and accepts one only if fresh answers show nothing got worse:

    ```bash
    modelbump repair propose suite.json report.json
    modelbump repair run suite.json modelbump-proposals --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none
    ```

    See [the scanner](architecture/scanner.md), [suites and `modelbump test`](architecture/suite.md), [prompt repair](architecture/repair.md), [the Phase 5 results on 40 real apps](research/suites.md) and [the repair results](research/repair.md). The upgrade pull request is still being built.

## Where to look

| Section | What you'll find |
|---------|------------------|
| [Architecture](architecture/index.md) | How the system is structured and why |
| [Decisions (ADRs)](adr/index.md) | Every significant technical decision, with the alternatives we rejected |
| [Engineering challenges](engineering-challenges/index.md) | Problems we hit while building, and how we solved them |
| [Dev journal](journal/index.md) | A short daily log of progress |
| [Research](research/index.md) | Research questions, experiment protocols and results |
