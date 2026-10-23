# ModelBump

**Dependabot for LLM models.** ModelBump finds the AI models your code depends on and warns you before a provider retires them. Later versions will also test the old model against its replacement, repair prompts that regress, and open the upgrade pull request for you.

!!! note "v0.1.0: the scanner"
    The first stage, **Scan**, is out as a command-line tool and a GitHub Action:

    ```bash
    pip install modelbump
    modelbump scan .
    ```

    See [the scanner](architecture/scanner.md) for the options and the Action. The other stages are still being built.

## Where to look

| Section | What you'll find |
|---------|------------------|
| [Architecture](architecture/index.md) | How the system is structured and why |
| [Decisions (ADRs)](adr/index.md) | Every significant technical decision, with the alternatives we rejected |
| [Engineering challenges](engineering-challenges/index.md) | Problems we hit while building, and how we solved them |
| [Dev journal](journal/index.md) | A short daily log of progress |
| [Research](research/index.md) | Research questions, experiment protocols and results |
