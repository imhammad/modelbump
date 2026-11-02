# ModelBump

**Dependabot for LLM models.** ModelBump finds the AI models your code depends on, warns you before a provider retires them, tests the replacement on your app's own prompts, repairs prompts that got worse, and opens the upgrade pull request for you.

!!! note "v1.0.0: scan, test, repair and bump"
    ModelBump finds the models your code uses and warns before they are retired. It tests the replacement on your app's own prompts, repairs prompts that got worse, and opens the pull request with the evidence:

    ```bash
    pip install modelbump
    modelbump scan .
    modelbump bump claude-3-haiku-20240307 --open-pr
    ```

    Start with the [tutorial](guide/tutorial.md): one app, from a retired model to a pull request, with free local models. The [user guide](guide/index.md) has the rest.

## Where to look

| Section | What you'll find |
|---------|------------------|
| [User guide](guide/index.md) | Tutorial, how it works, the GitHub Action, every command, FAQ |
| [Architecture](architecture/index.md) | How the system is structured and why |
| [Decisions (ADRs)](adr/index.md) | Every significant technical decision, with the alternatives we rejected |
| [Engineering challenges](engineering-challenges/index.md) | Problems we hit while building, and how we solved them |
| [Dev journal](journal/index.md) | A short daily log of progress |
| [Research](research/index.md) | Research questions, experiment protocols and results |
