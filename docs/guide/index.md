# User guide

ModelBump moves an app off an LLM model that its provider is retiring. It finds the model in your code, tests the replacement on your app's own prompts, repairs prompts that got worse, and opens the pull request, with the test results as evidence.

| Page | Read it when |
|------|--------------|
| [Tutorial](tutorial.md) | You want to try the whole flow once, on a small demo app, with free local models |
| [How it works](how-it-works.md) | You want to know what each step does and why you can trust its result |
| [GitHub Action](action.md) | You want warnings in CI, or bump pull requests on a schedule |
| [Command reference](cli.md) | You need every option of a command |
| [Python API and stability](python-api.md) | You use ModelBump from Python, or want to know what 1.x keeps stable |
| [FAQ](faq.md) | You have a question about cost, privacy, providers or languages |
