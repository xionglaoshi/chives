# Chives 技能来源与许可

此文件随 Chives 技能分发。下列记录保留各批研究方法、报告模板和配套资料的来源与改动说明。

## LangAlpha

本声明列出的技能迁移自 **LangAlpha** 仓库：
<https://github.com/ginlix-ai/langalpha>，源目录为 `plugins/langalpha_deliverables/skills/`、
`plugins/langalpha_research/skills/`、`plugins/langalpha_service/skills/`。

原项目以 **Apache License 2.0** 许可发布（见源仓库根目录的 `LICENSE`）。原仓库的版权与许可声明归其原作者所有；本目录不改变原许可条款。

**已修改（modified）**：迁移到 dsh 时对正文做了适配，包括按 `docs/tool-alias-map.md` 改写工具名、把 dsh 不存在的平台能力改为 web_search/web_fetch 或删除、把 `run-workflow` 的脚本调用改为 dsh `workflow` 工具的实际参数与语法、删除 LangAlpha 沙箱路径与界面专属描述。逐项改动见 `docs/skill-migration-T20.md`；未改动的原文段落保持原样。

迁移的 skill：`ui-design`、`competitive-analysis`、`research-conventions`、`sector-overview`、`thesis-tracker`、`trade-pitch`、`run-workflow`。

批次 2（T81）新增：`company-profile`、`comps-analysis`、`earnings-analysis`、`earnings-preview`、`morning-note`。逐项改动见 `docs/skill-migration-T81.md`；同样保留 Apache-2.0 许可与原作者版权声明。

批次 3（T82）新增：`dcf-model`、`3-statements`、`initiating-coverage`、`catalyst-calendar`、`idea-generation`。逐项改动见 `docs/skill-migration-T82.md`；同样保留 Apache-2.0 许可与原作者版权声明。

批次 4（T84）新增：`check-deck`、`check-model`、`model-update`、`impact-analysis`。逐项改动见 `docs/skill-migration-T84.md`；同样保留 Apache-2.0 许可与原作者版权声明。

批次 5（T88）新增：`web-scraping`、`x-api`。源目录为 `plugins/alternative_data/skills/`。逐项改动见 `docs/skill-migration-T88.md`；同样保留 Apache-2.0 许可与原作者版权声明。

批次 6（T90）新增：`portfolio-diagnosis`。源目录为 `plugins/langalpha_research/skills/`。逐项改动见 `docs/skill-migration-T90.md`；同样保留 Apache-2.0 许可与原作者版权声明。

批次 7（T92）新增：`subagent-roles`。其 5 个角色提示迁移自 LangAlpha（Apache-2.0）的 `src/ptc_agent/agent/prompts/templates/subagents/roles/` 与 `src/ptc_agent/agent/subagents/builtins.py` 中的角色分工；逐项改动见 `docs/skill-migration-T92.md`；同样保留 Apache-2.0 许可与原作者版权声明。

批次 8（T120，2026-11-16）：`earnings-analysis`、`comps-analysis`、`idea-generation`、`morning-note` 四个 skill 已针对 **A 股**大幅改写。范围包括：删除全部美股取数分支与美股工具引用，按 A 股定期报告、业绩预告/快报、预约披露、交易所公告与互动易重排主线，改接 `cn_data`、`cn_extra`、`cn_research`、`market_watch` 的现有工具，并重写 `references/` 下的美股参考文件。原有 Apache-2.0 许可与原作者版权声明不变；逐项改动见 `docs/skill-migration-T120.md`。

批次 9（T151，2026-11-17）：`trade-pitch`、`thesis-tracker`、`initiating-coverage`、`company-profile`、`competitive-analysis`、`sector-overview`、`catalyst-calendar`、`earnings-preview`、`impact-analysis` 九个 skill 针对 **A 股 + 本机只读数据网关**改写：删除美股/港股工具分支、期权与融券结构、Excel/PPT 模板，工具名改为 `market_*`/`company_*`/`news`/`convertible_bonds`/`watch_plan_*`，交付改为 Markdown + matplotlib。`initiating-coverage` 的 11 个美股/Excel 参考文件合并为 3 个 A 股参考文件。原有 Apache-2.0 许可与原作者版权声明不变；逐项改动见 `docs/skill-migration-T151.md`。

### 许可原文

```text
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to the Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   Copyright 2025 Ginlix AI

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```

## Vibe-Trading

cn_data 的十项只读数据方法使用同一项目提交 `cb99dca528695ffe78429483a90399a89f61d614` 的 Python 实现。Chives 的 MCP 适配器负责列举与调用。构建脚本随运行组件保留上游 LICENSE 和 NOTICE。

本声明列出的技能迁移自 **Vibe-Trading** 仓库：
<https://github.com/HKUDS/Vibe-Trading>，源目录为 `agent/src/skills/`。

原项目以 **MIT License** 许可发布（见源仓库根目录的 `LICENSE`）。原仓库的版权与许可声明归其原作者所有；本目录不改变原 MIT 许可条款。

**已修改（modified）**：迁移到 dsh 时对正文做了适配，包括按 `docs/tool-alias-map.md` 改写工具名（如 `read_url` → `web_fetch`）、删除 dsh 不存在的平台能力与界面专属描述、补充 A 股/港股规则与数据日期要求、删除无出处的统计/概率/评级/目标价表述、修正事实与公式错误。逐项改动见 `docs/skill-migration-T61.md`；未改动的原文段落保持原样。

本批迁移的 skill：`investor-lenses`、`dividend-analysis`、`research-discipline`、`web-reader`、`regulatory-knowledge`、`financial-statement`、`valuation-model`、`convertible-bond`、`earnings-forecast`、`report-generate`。

T63 追加迁移（加密类，质量筛选后保留）：`perp-funding-basis`、`defi-yield`、`okx-market`。逐项改动见 `docs/skill-migration-T63.md`。

### 许可原文

```text
MIT License

Copyright (c) 2026 Vibe-Trading Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 通讯频道扫码与协议适配

部分配对函数及协议适配参考 [Nous Research / Hermes Agent](https://github.com/NousResearch/hermes-agent/tree/8d70b88abd68fd58833ba0fc1f78ab209d213ed8)。

MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


## Pixelarticons 2.4.2

Bot 图标库使用 [Pixelarticons](https://github.com/halfmage/pixelarticons) 免费版的 SVG 路径。

MIT License

Copyright (c) 2019 Gerrit Halfmann

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

