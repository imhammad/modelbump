# ModelBump

**Dependabot for LLM models.** ModelBump finds the AI models your code depends on and warns you before a provider retires them. Later versions will also test the old model against its replacement, repair prompts that regress, and open the upgrade pull request for you.

!!! note "v0.3.0: the scanner, the runner and the statistics engine"
    The first stage, **Scan**, is out as a command-line tool and a GitHub Action:

    ```bash
    pip install modelbump
    modelbump scan .
    ```

    See [the scanner](architecture/scanner.md) for the options and the Action. Two building blocks for the next stages are out too: [the model runner](architecture/runner.md) (`modelbump ask`) and [the statistics engine](architecture/stats.md) (`modelbump stats`), which tells a real regression from normal LLM randomness. The other stages are still being built.

## Where to look

| Section | What you'll find |
|---------|------------------|
| [Architecture](architecture/index.md) | How the system is structured and why |
| [Decisions (ADRs)](adr/index.md) | Every significant technical decision, with the alternatives we rejected |
| [Engineering challenges](engineering-challenges/index.md) | Problems we hit while building, and how we solved them |
| [Dev journal](journal/index.md) | A short daily log of progress |
| [Research](research/index.md) | Research questions, experiment protocols and results |
