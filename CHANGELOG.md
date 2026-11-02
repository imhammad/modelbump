# Changelog

## [1.0.0](https://github.com/imhammad/modelbump/compare/v0.5.0...v1.0.0) (2026-11-02)


### Features

* **bump:** add test evidence and write accepted repairs into the code ([#97](https://github.com/imhammad/modelbump/issues/97)) ([fc8e505](https://github.com/imhammad/modelbump/commit/fc8e5052356d20461422ecdc40ee12718d0dc985))
* **bump:** change a model ID where the code uses it ([#94](https://github.com/imhammad/modelbump/issues/94)) ([f039987](https://github.com/imhammad/modelbump/commit/f039987c5bc278ad517e5be040045cd6818f8842))
* **bump:** move hard-coded model IDs to an environment variable ([#96](https://github.com/imhammad/modelbump/issues/96)) ([39cda2a](https://github.com/imhammad/modelbump/commit/39cda2a638c94d87367ba3a4ad38689682614bc4))
* **bump:** open bump pull requests on a schedule ([#99](https://github.com/imhammad/modelbump/issues/99)) ([78bfec6](https://github.com/imhammad/modelbump/commit/78bfec6eba9df4e3830a47928a7cc432ea3793aa))
* **bump:** open the pull request with the evidence report ([#98](https://github.com/imhammad/modelbump/issues/98)) ([6294dd7](https://github.com/imhammad/modelbump/commit/6294dd7e9e38a2df48856d8e3978b08a3bc1ec4b))
* **bump:** redact secrets from the evidence and scan large repositories faster ([#100](https://github.com/imhammad/modelbump/issues/100)) ([8b41271](https://github.com/imhammad/modelbump/commit/8b412710c8678701a43cfe036ebb0163dcba7e04))
* user guide, the 1.x stability promise and the v1 Action tag ([#101](https://github.com/imhammad/modelbump/issues/101)) ([81d44a8](https://github.com/imhammad/modelbump/commit/81d44a8491e0c70e54ab84b7891c77d4fcdb4907))

## [0.5.0](https://github.com/imhammad/modelbump/compare/v0.4.0...v0.5.0) (2026-10-31)


### Features

* **repair:** candidate patches from a local model ([#86](https://github.com/imhammad/modelbump/issues/86)) ([90732b6](https://github.com/imhammad/modelbump/commit/90732b6f832fbf83748eb9df7fd7d2e5389c8f06))
* **repair:** naive and iterative baselines ([#89](https://github.com/imhammad/modelbump/issues/89)) ([7589abf](https://github.com/imhammad/modelbump/commit/7589abf09035edf69b57f34b117b20acc9e5f989))
* **repair:** prompt patches tested on the new model only ([#84](https://github.com/imhammad/modelbump/issues/84)) ([b4f42cf](https://github.com/imhammad/modelbump/commit/b4f42cffe4f4927e31bdf15458993dcdef373bf6))
* **repair:** screen candidates, confirm on fresh answers ([#87](https://github.com/imhammad/modelbump/issues/87)) ([9b169d7](https://github.com/imhammad/modelbump/commit/9b169d741fd7b23aaac823507c1b3ed21e9d9115))
* **research:** RQ3 repair experiment on two migrations ([#90](https://github.com/imhammad/modelbump/issues/90)) ([0cf5df9](https://github.com/imhammad/modelbump/commit/0cf5df9e847cc129e283e13956928d9ecf4bf08b))


### Bug Fixes

* **research:** count proposer requests apart from the judge ([#92](https://github.com/imhammad/modelbump/issues/92)) ([802b82e](https://github.com/imhammad/modelbump/commit/802b82ea80ec9faced96151a2966008bf48b6cc4))
* **research:** second migration uses Qwen 3 4B Instruct ([#91](https://github.com/imhammad/modelbump/issues/91)) ([35de866](https://github.com/imhammad/modelbump/commit/35de866998bb73be1c2de2e9612658fcdda909bd))


### Documentation

* **paper:** the author's rewrite of every section ([#88](https://github.com/imhammad/modelbump/issues/88)) ([8aaf6ab](https://github.com/imhammad/modelbump/commit/8aaf6ab6595834eee49cbf94c15e61e61b220aa1))
* **repair:** RQ3 results and README for v0.5.0 ([#93](https://github.com/imhammad/modelbump/issues/93)) ([3686390](https://github.com/imhammad/modelbump/commit/368639052bd3564d8eeb6d96c166f582c5f2c446))

## [0.4.0](https://github.com/imhammad/modelbump/compare/v0.3.0...v0.4.0) (2026-10-29)


### Features

* **oracles:** bigger judge that fails invented facts ([#77](https://github.com/imhammad/modelbump/issues/77)) ([d1dccb3](https://github.com/imhammad/modelbump/commit/d1dccb3b0aaf26efb99f65dfd8cae4b54486dd3e))
* **oracles:** blind label sheet and judge agreement ([#76](https://github.com/imhammad/modelbump/issues/76)) ([bb5e693](https://github.com/imhammad/modelbump/commit/bb5e6936068c20e9dc2b73dcf54bab90042b0b8e))
* **oracles:** judge probes with answers broken on purpose ([#79](https://github.com/imhammad/modelbump/issues/79)) ([24f79d9](https://github.com/imhammad/modelbump/commit/24f79d93fe1f44cedf7bb2abbf858f5344b4ccb6))
* **oracles:** LLM judge for free-text answers ([#75](https://github.com/imhammad/modelbump/issues/75)) ([e5334dc](https://github.com/imhammad/modelbump/commit/e5334dc735256d2c5deeb689c42e1eaa4886960a))
* **oracles:** pick an oracle per call and score answers against the old model ([#73](https://github.com/imhammad/modelbump/issues/73)) ([023c672](https://github.com/imhammad/modelbump/commit/023c672750d8e6ddd78673d6a56cd9ce629aa3d3))
* **research:** benchmark corpus of real LLM apps ([#78](https://github.com/imhammad/modelbump/issues/78)) ([6276581](https://github.com/imhammad/modelbump/commit/62765813400e6c14e639dd4ed499cbee18556284))
* **research:** run the corpus end to end ([#80](https://github.com/imhammad/modelbump/issues/80)) ([738dcd9](https://github.com/imhammad/modelbump/commit/738dcd97dba495e860e690ce2aa13fbc9c645d5c))
* **suite:** suite file and modelbump test on two models ([#74](https://github.com/imhammad/modelbump/issues/74)) ([fbb37f5](https://github.com/imhammad/modelbump/commit/fbb37f54b8d2305dc7632770e8f6121119e14693))
* **synth:** find LLM calls and their prompt templates ([#68](https://github.com/imhammad/modelbump/issues/68)) ([16dbd13](https://github.com/imhammad/modelbump/commit/16dbd13833300369f09e187464049267522c77f6))
* **synth:** follow prompts into other files, classes and prompt functions ([#70](https://github.com/imhammad/modelbump/issues/70)) ([ea7e3ce](https://github.com/imhammad/modelbump/commit/ea7e3ce5c65ceff93d01cd2a5fe588e8aadce60a))
* **synth:** generated test inputs from a local model ([#72](https://github.com/imhammad/modelbump/issues/72)) ([9d50746](https://github.com/imhammad/modelbump/commit/9d50746beccd72a7a707d070cfbd3da9abc66b7a))
* **synth:** test inputs from the app's own tests and callers ([#71](https://github.com/imhammad/modelbump/issues/71)) ([5c9d860](https://github.com/imhammad/modelbump/commit/5c9d86092e40927ec27e8e869447e8687daabf98))


### Bug Fixes

* **oracles:** judge fails made-up specifics about the app ([#82](https://github.com/imhammad/modelbump/issues/82)) ([4dfe059](https://github.com/imhammad/modelbump/commit/4dfe059126e1a69468e3ac5d5967985ad84ec92e))
* **oracles:** judge instructions from the corpus labels ([#81](https://github.com/imhammad/modelbump/issues/81)) ([8b1e29d](https://github.com/imhammad/modelbump/commit/8b1e29df63aa3cd79fe6475cdc27440a6965c096))


### Documentation

* phase 5 results and README for v0.4.0 ([#83](https://github.com/imhammad/modelbump/issues/83)) ([0fde252](https://github.com/imhammad/modelbump/commit/0fde252b4d64c42e049ae095205733ae10dd9a77))

## [0.3.0](https://github.com/imhammad/modelbump/compare/v0.2.0...v0.3.0) (2026-10-27)


### Features

* **research:** add the real-model results, figures and token counts (ADR 0047) ([#67](https://github.com/imhammad/modelbump/issues/67)) ([eec8049](https://github.com/imhammad/modelbump/commit/eec8049c3b56e67b64cd67571d03df8d0c467b5b))
* **research:** test the stats engine on real local models (ADR 0046) ([#66](https://github.com/imhammad/modelbump/issues/66)) ([5223a3e](https://github.com/imhammad/modelbump/commit/5223a3e7a7c565c36e6abf17291b5eae488a9b83))
* **stats:** accept scores between 0 and 1 and stop cases that look fine (ADR 0045) ([#65](https://github.com/imhammad/modelbump/issues/65)) ([ea2d6ed](https://github.com/imhammad/modelbump/commit/ea2d6edbe06b255a5ba32172e40153cb8eaf49d0))
* **stats:** add a simulation study and property tests for the stats engine (ADR 0044) ([#64](https://github.com/imhammad/modelbump/issues/64)) ([3d788ff](https://github.com/imhammad/modelbump/commit/3d788ff9745f7dcd631a833c828b8f4e39057ef1))
* **stats:** control false alarms across a suite with e-BH (ADR 0043) ([#63](https://github.com/imhammad/modelbump/issues/63)) ([c364c14](https://github.com/imhammad/modelbump/commit/c364c14c97988eabf497a593665b392186660936))
* **stats:** decide one test case from pass counts (ADR 0041) ([#60](https://github.com/imhammad/modelbump/issues/60)) ([dccad04](https://github.com/imhammad/modelbump/commit/dccad04b8fdd7b484a829d9b3144dade92aaea9e))
* **stats:** stop sampling as soon as the verdict is clear (ADR 0042) ([#62](https://github.com/imhammad/modelbump/issues/62)) ([8b51322](https://github.com/imhammad/modelbump/commit/8b5132296cec5541f81bfa013898815351d66be9))

## [0.2.0](https://github.com/imhammad/modelbump/compare/v0.1.0...v0.2.0) (2026-10-27)


### Features

* **runner:** add free cloud tiers with request pacing (ADR 0040) ([#59](https://github.com/imhammad/modelbump/issues/59)) ([14f30d2](https://github.com/imhammad/modelbump/commit/14f30d2f5a558f95b14e986ef7fc3687a6934fb9))
* **runner:** cache model answers by a hash of the request (ADR 0037) ([#56](https://github.com/imhammad/modelbump/issues/56)) ([02f80dd](https://github.com/imhammad/modelbump/commit/02f80dd0e130ea7c6f0a2c3458980094108d96c3))
* **runner:** call local models with retries and timeouts (ADR 0036) ([#54](https://github.com/imhammad/modelbump/issues/54)) ([29b33e7](https://github.com/imhammad/modelbump/commit/29b33e7ca222aa4e3a52f3fbc47b963981487ec6))
* **runner:** limit tokens and requests per run (ADR 0038) ([#57](https://github.com/imhammad/modelbump/issues/57)) ([eaaf8c9](https://github.com/imhammad/modelbump/commit/eaaf8c95c91844ad7c85017550b57a1aee4bf7a8))
* **runner:** pin local models to their digest, add models and --think (ADR 0039) ([#58](https://github.com/imhammad/modelbump/issues/58)) ([a56d79a](https://github.com/imhammad/modelbump/commit/a56d79a3ee52c95ad2ac6fa56bf863ccc8efec19))

## [0.1.0](https://github.com/imhammad/modelbump/compare/v0.0.1...v0.1.0) (2026-10-23)


### Features

* **action:** GitHub Action for model retirement checks ([#43](https://github.com/imhammad/modelbump/issues/43)) ([462a2db](https://github.com/imhammad/modelbump/commit/462a2db84e5268783c138e25623eed3997268ae1))
* **filtering:** rules v2 with migration_away label and in-sample check ([#23](https://github.com/imhammad/modelbump/issues/23)) ([b647f34](https://github.com/imhammad/modelbump/commit/b647f34675a2b75cdb482d261cb14e8941821d5d))
* **paper:** LaTeX draft of Paper 1 with a CI build ([#37](https://github.com/imhammad/modelbump/issues/37)) ([c53daa9](https://github.com/imhammad/modelbump/commit/c53daa9229169c44cf818dc73349c7ac5b62f72a))
* **registry:** OpenAI and Google retirements ([#12](https://github.com/imhammad/modelbump/issues/12)) ([59bdf08](https://github.com/imhammad/modelbump/commit/59bdf088639458e922225fdc81ae963cd4447dd6))
* **registry:** retirement registry v1 ([#10](https://github.com/imhammad/modelbump/issues/10)) ([7fdf250](https://github.com/imhammad/modelbump/commit/7fdf250b37ca62dd89694c4b06717b0f14c5f316)), closes [#9](https://github.com/imhammad/modelbump/issues/9)
* **research:** blind stratified sample for hand-labelling ([#21](https://github.com/imhammad/modelbump/issues/21)) ([c274ad6](https://github.com/imhammad/modelbump/commit/c274ad69dba70cc937924dfd5437cdf2b01b1e68))
* **research:** build the paper's numbers, tables and figures ([#33](https://github.com/imhammad/modelbump/issues/33)) ([d3c8f73](https://github.com/imhammad/modelbump/commit/d3c8f733455b1d772180096e407a4c886a18aa79))
* **research:** changed files of a migration sample (RQ4) ([#30](https://github.com/imhammad/modelbump/issues/30)) ([febc750](https://github.com/imhammad/modelbump/commit/febc75032a6be063cdae37801435007cce32b88b))
* **research:** hybrid search for huge model IDs and network retries ([#17](https://github.com/imhammad/modelbump/issues/17)) ([640c3b9](https://github.com/imhammad/modelbump/commit/640c3b9d7c0709d0087c58ec4b020d5692c883c7))
* **research:** label migration commits with Kim's rules ([#20](https://github.com/imhammad/modelbump/issues/20)) ([f992c96](https://github.com/imhammad/modelbump/commit/f992c961e37bca3e104356152015b7a95f7f8b83))
* **research:** migration lag and target models (RQ2, RQ3) ([#28](https://github.com/imhammad/modelbump/issues/28)) ([8267ece](https://github.com/imhammad/modelbump/commit/8267ece384a2e72162aa17890f3e2b6b937fc5f9))
* **research:** package the dataset for Zenodo ([#34](https://github.com/imhammad/modelbump/issues/34)) ([b110921](https://github.com/imhammad/modelbump/commit/b1109215c544eb1f189bf306c6b03ec9ad29a657))
* **research:** place migrations on the retirement timeline ([#26](https://github.com/imhammad/modelbump/issues/26)) ([0297137](https://github.com/imhammad/modelbump/commit/02971375827e828107c077866b0c0f123c501c44))
* **research:** re-score the scanner labels after a scanner change ([#49](https://github.com/imhammad/modelbump/issues/49)) ([6bfddc9](https://github.com/imhammad/modelbump/commit/6bfddc9bfdd3c1f7d14ac93e204dca01f2513724))
* **research:** replay the scanner before real migrations ([#50](https://github.com/imhammad/modelbump/issues/50)) ([017a4ed](https://github.com/imhammad/modelbump/commit/017a4ed31c7a70d40ec00d4861e0b2d3690f5410))
* **research:** replay warning sources and first-pass re-scoring ([#51](https://github.com/imhammad/modelbump/issues/51)) ([49049f9](https://github.com/imhammad/modelbump/commit/49049f9e0007b3b9ea2a50bb8ba7c378d6c136af))
* **research:** robustness checks for RQ1 and RQ2 ([#35](https://github.com/imhammad/modelbump/issues/35)) ([6bea6cb](https://github.com/imhammad/modelbump/commit/6bea6cb04014cd4bd59ec9fcd410c8087a4122a8))
* **research:** scanner evaluation set from real migrations ([#46](https://github.com/imhammad/modelbump/issues/46)) ([afbdff5](https://github.com/imhammad/modelbump/commit/afbdff5659cf10ebfb8426fb131be7c06afde0be))
* **research:** score the scanner's precision labels ([#47](https://github.com/imhammad/modelbump/issues/47)) ([1e1c637](https://github.com/imhammad/modelbump/commit/1e1c6374844034dcf43ffd61826a2c12f549608c))
* **scanner:** context for each finding, with tree-sitter for Python ([#44](https://github.com/imhammad/modelbump/issues/44)) ([cc86a75](https://github.com/imhammad/modelbump/commit/cc86a753fe19317fbb3d8bc4ef956b06eee39ee7))
* **scanner:** context for TypeScript and JavaScript findings ([#45](https://github.com/imhammad/modelbump/issues/45)) ([bf23767](https://github.com/imhammad/modelbump/commit/bf23767a9b9d70f848b745a7f296b2274b6c1c84))
* **scanner:** find model IDs in code and config ([#40](https://github.com/imhammad/modelbump/issues/40)) ([53e4f42](https://github.com/imhammad/modelbump/commit/53e4f421f196199eaf05d7f28db7dc18f3b3adfe))
* **scanner:** JSON and SARIF reports ([#42](https://github.com/imhammad/modelbump/issues/42)) ([33afb07](https://github.com/imhammad/modelbump/commit/33afb079a4da515de8a88a0c450df9cc3cfcdbd8))
* **scanner:** mark IDs that only describe a model, add --skip-tests ([#48](https://github.com/imhammad/modelbump/issues/48)) ([b846fe3](https://github.com/imhammad/modelbump/commit/b846fe3fc48797b931ae8dbbdc0eb281d7daf18b))
* **scanner:** severity levels and a CI exit code ([#41](https://github.com/imhammad/modelbump/issues/41)) ([3d47de5](https://github.com/imhammad/modelbump/commit/3d47de58f7c74a13f6a499f87e7d08deb44a3c7a))
* **validation:** fresh blind sample to measure rules v2 ([#24](https://github.com/imhammad/modelbump/issues/24)) ([da754b8](https://github.com/imhammad/modelbump/commit/da754b85b4d6e94ad786326485cd71ffb099ed26))
* **validation:** score hand labels with Wilson intervals and kappa ([#22](https://github.com/imhammad/modelbump/issues/22)) ([e4a6637](https://github.com/imhammad/modelbump/commit/e4a6637c79761681bd56ea0fa39cf58c9640245c))


### Bug Fixes

* **mining:** gentler search pace and longer back-off ([#16](https://github.com/imhammad/modelbump/issues/16)) ([a57c1cd](https://github.com/imhammad/modelbump/commit/a57c1cdef4e574b12e021fbe8b22dcd280c9dba7)), closes [#15](https://github.com/imhammad/modelbump/issues/15)
* **paper:** follow EMSE's guidelines and report the first-pass precision ([#38](https://github.com/imhammad/modelbump/issues/38)) ([0e27d70](https://github.com/imhammad/modelbump/commit/0e27d7048ba74ffec5946c3c9965551f9ba5fc76))
* **release:** use v-prefixed tags without component name ([#7](https://github.com/imhammad/modelbump/issues/7)) ([b6d771a](https://github.com/imhammad/modelbump/commit/b6d771ace5f9cf61057db71af867a8384b6abfe3))
* **research:** file rules from the hand check ([#32](https://github.com/imhammad/modelbump/issues/32)) ([3ae1550](https://github.com/imhammad/modelbump/commit/3ae15504e34bb6488848bda4b37511b26e525272))
* **research:** follow redirects for renamed repositories ([#31](https://github.com/imhammad/modelbump/issues/31)) ([993a69a](https://github.com/imhammad/modelbump/commit/993a69a904d4f454a8e3f549f816177a62741313))
* **research:** retry GitHub server errors and split windows that keep failing ([#19](https://github.com/imhammad/modelbump/issues/19)) ([c1b53ad](https://github.com/imhammad/modelbump/commit/c1b53adad4af87bc7f344a6746725448f563a6b2))
* **research:** search huge model IDs only from 30 days before the notice ([#18](https://github.com/imhammad/modelbump/issues/18)) ([f52016a](https://github.com/imhammad/modelbump/commit/f52016aaabac9eac1004c49e92bbdf9a1e91be4d))
* **research:** target rules tuned on the first sample ([#29](https://github.com/imhammad/modelbump/issues/29)) ([31ea776](https://github.com/imhammad/modelbump/commit/31ea7762156f32d3f4434f3a805726e09f84be0d))
* **research:** weight up the days GitHub cut instead of dropping models ([#36](https://github.com/imhammad/modelbump/issues/36)) ([fad474d](https://github.com/imhammad/modelbump/commit/fad474dfce9819d496f8508d7be35551b50977f3))


### Research

* **mining:** commit-search miner ([#14](https://github.com/imhammad/modelbump/issues/14)) ([680c7e9](https://github.com/imhammad/modelbump/commit/680c7e976081792dbf3bef97f6c8b9d42eb8e3b1))


### Documentation

* journal entry for 2026-10-08 ([#8](https://github.com/imhammad/modelbump/issues/8)) ([8c6d689](https://github.com/imhammad/modelbump/commit/8c6d68921a5c7109bdfed63a9b0e4310f1469b5d))
* **paper:** related work with 36 checked references ([#39](https://github.com/imhammad/modelbump/issues/39)) ([6ca0b11](https://github.com/imhammad/modelbump/commit/6ca0b11a148d0fead19c943af26b1b1ea29d13e7))
* **research:** dataset card and migration timing results ([#27](https://github.com/imhammad/modelbump/issues/27)) ([530c02a](https://github.com/imhammad/modelbump/commit/530c02aa815c5e3ceb28f873a55b7455b3b86f0d))
* Scoring section in docs/research/validation.md. ([e4a6637](https://github.com/imhammad/modelbump/commit/e4a6637c79761681bd56ea0fa39cf58c9640245c))
* **validation:** record rules v2 results and challenge 006 ([#25](https://github.com/imhammad/modelbump/issues/25)) ([cf460f5](https://github.com/imhammad/modelbump/commit/cf460f50322772814c9b3487be15faf573da8ad0))
