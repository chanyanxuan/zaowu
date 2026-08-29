# 第三方组件声明 (Third-Party Notices)

本仓库直接包含或引用了以下开源项目,特此致谢并说明其许可。

## 代码依赖与派生

| 组件 | 来源 | 许可 | 用途 |
|---|---|---|---|
| text-to-cad | https://github.com/earthtojake/text-to-cad | MIT | 生成管线与技能体系的底座 |
| cadgen | 同上(text-to-cad 内 skills/cad) | MIT | 代码生成 / 快照 / 导出 CLI |
| CAD Viewer | https://github.com/earthtojake/text-to-cad(skills/cad-viewer) | MIT | 三维预览器(本仓库 `cad-viewer-src/` 为汉化定制版) |
| build123d | https://github.com/gumyr/build123d | Apache-2.0 | 参数化建模内核 |
| cadquery-ocp | https://github.com/CadQuery/OCP | Apache-2.0 | OpenCascade Python 绑定 |
| Flask | https://github.com/pallets/flask | BSD-3-Clause | Web 框架 |
| OpenSCAD | https://openscad.org | GPL-2.0(仅以独立进程渲染,不链接) | 打印件渲染 |
| Space Grotesk | https://github.com/floriankarsten/space-grotesk | OFL-1.1 | 页面英文字体 |

## 标准件库引用的开源库

| 组件 | 来源 | 许可 | 用法 |
|---|---|---|---|
| BOSL2 | https://github.com/BelfrySCAD/BOSL2 | BSD-3-Clause | 直齿轮 / 螺纹杆模板(OpenSCAD 渲染) |
| dotSCAD | https://github.com/JustinSDK/dotSCAD | MIT | 晶格球模板(OpenSCAD 渲染) |
| Gridfinity Rebuilt | https://github.com/kennetek/gridfinity-rebuilt-openscad | MIT | 收纳底座模板(OpenSCAD 渲染) |
| NopSCADlib | https://github.com/nophead/NopSCADlib | GPL-3.0 | **仅作尺寸数据表参考,未并入任何代码** |

## 数据来源

- step.parts(https://www.step.parts):外部零件检索的数据源,由 earthtojake 维护;每个 STEP 件遵循其各自来源的许可,下载时请自行核对。
- 标准件尺寸表:依据 GB/T、ISO 公开标准整理,标注为「工程近似值」,不构成选型依据。

## 字体

- Space Grotesk(web/fonts/),SIL Open Font License 1.1

如需补充或更正,欢迎提交 Issue / PR。
