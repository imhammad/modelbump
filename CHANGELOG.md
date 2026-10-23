# Changelog

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
