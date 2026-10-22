# ADR 0028: TypeScript and JavaScript context, and option objects as call arguments

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

[ADR 0027](0027-python-context-with-tree-sitter.md) gave Python findings their context. Many LLM apps are written in TypeScript or JavaScript (OpenAI's and Anthropic's Node SDKs, the Vercel AI SDK, LangChain.js), and their findings still had no context. JavaScript SDKs pass the model inside an options object, `openai.chat.completions.create({ model: "gpt-4o" })`, or as a plain argument, `google("gemini-2.5-pro")`. Code also often falls back to a default, `process.env.MODEL ?? "gpt-4o"`.

## Decision

- **Parse with `tree-sitter-typescript`,** which has two grammars. `.ts`, `.mts` and `.cts` use the TypeScript grammar. `.tsx`, `.js`, `.jsx`, `.mjs` and `.cjs` use the TSX grammar: JavaScript files often contain JSX, and TypeScript's `<T>value` casts would be read as JSX by the TSX grammar.
- **The same contexts as Python**, with JavaScript's forms:
  - `call_argument`: a value in an options object passed to a call or `new` (`create({model})`, `new ChatOpenAI({modelName})`), or a positional argument (`google(argument 1)`);
  - `assignment`: `const`/`let`/`var`, assignments, class fields, parameter defaults and destructuring defaults;
  - `string`: other strings, with the key for an object value or a JSX attribute;
  - `comment`: line, block and JSDoc comments. JavaScript has no docstrings.
- **Look through wrappers** to find what uses the string: parentheses, `as` and `satisfies`, `??`/`||` fallbacks and `? :`. So `const model = process.env.MODEL ?? "gpt-4o"` is an `assignment` to `model`.
- **The GitHub Action gets a `skip-comments` input,** passed to `--skip-comments`.

## Alternatives considered

- **`tree-sitter-javascript` for `.js` files:** one more dependency, and the TSX grammar already parses JavaScript with JSX.
- **Treat an options object as a plain `string` with its key:** simpler, but it hides the call, which is what a user needs to find to change the model.
- **Run Node or the TypeScript compiler:** exact types, but it would need Node.js and a project's own setup on every machine that runs the scanner.

## Consequences

- One new prebuilt dependency (`tree-sitter-typescript`, wheels for macOS, Linux and Windows).
- `.ipynb`, `.go`, `.java` and other files keep context `text` until they get a parser.
- The fallback rule makes a default value look like the model in use, even when an environment variable usually overrides it. The finding is still right to warn: the default is what runs when the variable is missing.
