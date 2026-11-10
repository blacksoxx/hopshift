# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/blacksoxx/vmware-migration-agent/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                 |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------- | -------: | -------: | ------: | --------: |
| agent/config\_loader.py              |      155 |       60 |     61% |31, 35-36, 39, 43, 48, 63, 69, 75, 97-99, 118, 122, 127, 130, 133, 143, 149, 156, 162, 164, 168, 174, 176, 186, 191-205, 209-213, 228, 230, 232-235, 240-251 |
| agent/generation/deterministic.py    |       83 |       10 |     88% |62, 70, 84, 91, 107, 136-137, 141, 149, 151 |
| agent/graph.py                       |       54 |        0 |    100% |           |
| agent/llm\_client.py                 |      395 |      147 |     63% |159-163, 215-216, 219, 238-243, 263, 275-276, 311, 344, 364, 378-420, 432-471, 481-488, 491-498, 501-503, 506-509, 530, 533-536, 540-542, 546, 574-581, 593, 598-611, 620-627, 631-650, 654-658, 700-704, 718, 732, 736, 738-740, 747, 751-754, 763-767 |
| agent/nodes/assess\_reporter.py      |       72 |        6 |     92% |25, 29, 71-81, 168 |
| agent/nodes/blocker\_parser.py       |       61 |        6 |     90% |19, 23, 33, 77, 81, 85 |
| agent/nodes/cim\_mapper.py           |       22 |        2 |     91% |    17, 21 |
| agent/nodes/enricher.py              |      131 |       35 |     73% |16, 20, 29, 54, 84, 86, 88, 95, 110, 115, 133, 138, 156-160, 165, 168-176, 181, 185-191 |
| agent/nodes/hcl\_generator.py        |      818 |      150 |     82% |38, 63, 74-75, 102, 141-145, 217-267, 332, 381, 436-452, 516-521, 529, 546-560, 587-588, 591, 604, 611, 618-619, 622-623, 628, 643-647, 654, 658, 660-663, 677, 705, 712, 715, 723, 738, 748-779, 799, 806, 814, 819-822, 923, 933, 944, 953-954, 982, 991, 1189, 1191, 1193, 1297, 1395, 1442, 1472-1473, 1523, 1575-1576, 1584-1585, 1597, 1664, 1676, 1678, 1831-1833, 1838-1841, 1846 |
| agent/nodes/ingest.py                |       78 |       31 |     60% |21-23, 27-28, 39-45, 49-58, 73, 81, 88-89, 93, 95, 100, 108, 115, 121-123, 128 |
| agent/nodes/mcp\_client.py           |      451 |      232 |     49% |93-94, 97-117, 126, 138-148, 151-184, 187-188, 191-195, 198-225, 228-257, 260-280, 283-290, 293-294, 297-301, 304-320, 329-335, 344, 370, 415, 433-434, 437-442, 446-447, 455, 487-488, 496, 503, 507, 520, 557, 566, 574, 583-631, 635-642, 655-665, 670-671, 679-694, 700, 719, 725, 742, 752, 759, 765, 768-775, 782-788, 792-795, 799-817, 821-832, 836-843 |
| agent/nodes/reporter.py              |      173 |       25 |     86% |28, 149-152, 191-199, 204, 217, 229, 244, 250, 261, 290, 305-309 |
| agent/nodes/risk\_assessor.py        |      248 |       67 |     73% |17, 21, 74-75, 78-79, 82-83, 86-87, 90-92, 100-101, 139-151, 160-161, 164-165, 168-169, 172-174, 182-184, 212-224, 233-234, 237-239, 242-243, 272-273, 276-278, 300-301, 304-306, 334-335, 366, 370, 381-382, 390-392, 395-397, 400-402, 426, 432, 435, 468 |
| agent/nodes/sizer.py                 |       46 |        7 |     85% |20, 24, 62, 75, 79-80, 86 |
| agent/nodes/validator.py             |      159 |       17 |     89% |70, 78-82, 133, 197, 232-233, 268, 293, 315, 321, 330-334 |
| agent/prompts.py                     |       34 |        3 |     91% |120-132, 157 |
| agent/runtime.py                     |      496 |       78 |     84% |95, 97, 99, 104, 145-146, 153-154, 162, 166-167, 181-183, 234-236, 258-261, 266-268, 274, 283-284, 295, 303-305, 311, 322, 399, 413, 416, 427, 435-449, 459-469, 475, 480-481, 524-525, 553, 576, 590-592, 639, 721-723, 733, 753 |
| agent/state.py                       |       54 |        0 |    100% |           |
| api/app.py                           |       68 |        7 |     90% |44-46, 83, 87, 104, 113 |
| api/deps.py                          |       44 |        1 |     98% |        61 |
| api/middleware.py                    |       58 |        8 |     86% |84, 86, 91-96 |
| api/routes/\_\_init\_\_.py           |       17 |        4 |     76% |     26-29 |
| api/routes/assess.py                 |       20 |        0 |    100% |           |
| api/routes/audit.py                  |       22 |        0 |    100% |           |
| api/routes/auth.py                   |      115 |        1 |     99% |       115 |
| api/routes/connections.py            |       59 |        1 |     98% |        41 |
| api/routes/deploy.py                 |       71 |        1 |     99% |        96 |
| api/routes/meta.py                   |       20 |        1 |     95% |        43 |
| api/routes/runs.py                   |      243 |       78 |     68% |105, 107, 109, 111, 120-136, 189-198, 210, 221-226, 241-243, 251-255, 297, 310-316, 330-348, 353-361 |
| api/routes/settings.py               |       36 |       15 |     58% |22, 37-46, 55, 59-64 |
| api/routes/users.py                  |       41 |        0 |    100% |           |
| api/serialization.py                 |       13 |        2 |     85% |    11, 17 |
| cim/blockers.py                      |       40 |        0 |    100% |           |
| cim/schema.py                        |      147 |        2 |     99% |  169, 241 |
| cim/schema\_export.py                |       29 |       13 |     55% |27, 31-41, 45 |
| cim/translators/\_\_init\_\_.py      |       26 |        0 |    100% |           |
| cim/translators/vmware.py            |      233 |       20 |     91% |149, 152-154, 165, 184, 218-220, 227, 246, 280, 295, 318, 331, 334, 392, 426, 430, 432 |
| cim/vmware\_translator.py            |        2 |        0 |    100% |           |
| cli/main.py                          |      401 |      124 |     69% |157-158, 162-167, 178-180, 195, 234-270, 286-296, 315-348, 388, 394, 410, 445, 452, 468, 476, 497-498, 520, 524, 545-554, 558-583, 589, 594-597, 601-609, 614, 651, 686, 703, 716-717, 719-720, 768, 797, 825, 829 |
| providers/aws/compute.py             |       71 |        2 |     97% |  107, 109 |
| providers/aws/network.py             |      101 |       21 |     79% |13, 80, 102-115, 160, 162, 170, 177, 181 |
| providers/aws/placement.py           |       50 |        5 |     90% |18, 46, 58, 69, 71 |
| providers/aws/runtime.py             |       11 |        0 |    100% |           |
| providers/aws/sizing\_table.py       |       23 |        2 |     91% |    37, 39 |
| providers/aws/storage.py             |       76 |        5 |     93% |64, 67, 98, 131, 133 |
| providers/azure/compute.py           |      113 |        6 |     95% |105-106, 128, 144, 152, 154 |
| providers/azure/network.py           |      133 |       23 |     83% |13, 74-81, 84-90, 129, 134, 152, 154, 162, 169, 173 |
| providers/azure/placement.py         |       57 |        5 |     91% |22, 58, 70, 81, 83 |
| providers/azure/runtime.py           |       11 |        0 |    100% |           |
| providers/azure/sizing\_table.py     |       23 |        2 |     91% |    37, 39 |
| providers/azure/storage.py           |       74 |        7 |     91% |30-31, 72, 75, 104, 118, 120 |
| providers/base.py                    |       31 |       31 |      0% |      1-52 |
| providers/common.py                  |       46 |        4 |     91% |     75-78 |
| providers/gcp/compute.py             |      127 |       12 |     91% |86-87, 112, 132, 140, 142, 153, 155, 165, 167, 170, 179 |
| providers/gcp/network.py             |      145 |       33 |     77% |13, 69-80, 83-93, 116, 155, 157, 168, 170, 180, 182, 197, 201 |
| providers/gcp/placement.py           |       48 |        7 |     85% |22, 29, 48, 56, 58, 66, 68 |
| providers/gcp/runtime.py             |       11 |        0 |    100% |           |
| providers/gcp/sizing\_table.py       |       23 |        2 |     91% |    37, 39 |
| providers/gcp/storage.py             |      105 |       14 |     87% |30-31, 76-77, 80-81, 106, 108, 125, 139, 141, 158, 160, 169 |
| providers/openstack/compute.py       |       92 |       11 |     88% |63-64, 89, 106, 130, 136-140, 148, 150 |
| providers/openstack/network.py       |      132 |       26 |     80% |13, 75-84, 87-95, 124, 152, 160, 162, 170, 174 |
| providers/openstack/placement.py     |       34 |        4 |     88% |19, 38, 46, 48 |
| providers/openstack/runtime.py       |       11 |        0 |    100% |           |
| providers/openstack/sizing\_table.py |       23 |        2 |     91% |    37, 39 |
| providers/openstack/storage.py       |       69 |        5 |     93% |64, 67, 94, 113, 115 |
| providers/runtime\_common.py         |       34 |        6 |     82% |39, 49, 51, 55-56, 58 |
| validation/hcl\_parser.py            |       72 |       18 |     75% |36, 39-41, 49-51, 90, 107, 110, 115, 125-129, 134-135 |
| validation/opa\_client.py            |      172 |       25 |     85% |30-33, 81-82, 107-108, 112-114, 123-124, 139-141, 145-147, 211-218, 314-315 |
| validation/paths.py                  |       19 |        1 |     95% |        30 |
| validation/tf\_runner.py             |       94 |       24 |     74% |22-23, 52, 76-82, 90-91, 107-108, 141, 158-163, 168-191 |
| vma/\_\_init\_\_.py                  |        1 |        0 |    100% |           |
| vma/audit.py                         |      103 |        1 |     99% |       175 |
| vma/compliance/\_\_init\_\_.py       |        3 |        0 |    100% |           |
| vma/compliance/controls.py           |       34 |        1 |     97% |        48 |
| vma/compliance/report.py             |      112 |        3 |     97% |48, 93, 226 |
| vma/connections/\_\_init\_\_.py      |        8 |        0 |    100% |           |
| vma/connections/aws.py               |      179 |       47 |     74% |32, 42-51, 62-65, 69-73, 83-84, 88-91, 95-96, 100-106, 113-115, 119-121, 158-159, 161, 191, 223, 239 |
| vma/connections/azure.py             |      168 |       29 |     83% |43, 53-56, 64, 117, 134-135, 140, 142-145, 153, 164-171, 217, 237-238, 240-241, 244 |
| vma/connections/gcp.py               |       87 |       25 |     71% |26, 38-44, 59-63, 68-71, 75-81, 111, 115, 122-123 |
| vma/connections/models.py            |      232 |       27 |     88% |67, 75, 127, 206-207, 219, 234, 443, 457-462, 464-471, 473-474, 477, 482-483 |
| vma/connections/openstack.py         |      110 |       25 |     77% |30-36, 48, 55-56, 83, 85-88, 92, 97, 105-106, 111-117, 165 |
| vma/connections/service.py           |      307 |       23 |     93% |112, 114, 126, 188-189, 223-224, 248-252, 268-269, 299, 313, 315, 350-351, 372-373, 375, 386-387 |
| vma/connections/store.py             |      109 |       13 |     88% |79-80, 119-120, 136-137, 139, 160, 171, 202, 207-209 |
| vma/db.py                            |       72 |        4 |     94% | 33, 65-67 |
| vma/deploy/\_\_init\_\_.py           |        9 |        0 |    100% |           |
| vma/deploy/service.py                |      404 |       36 |     91% |138, 140, 175, 192-193, 223, 279, 319, 321-322, 334-337, 371, 381, 391, 404, 406, 409-410, 428-429, 466, 520, 532, 535-538, 549-550, 569, 575-576, 595 |
| vma/deploy/store.py                  |       85 |        3 |     96% |104, 140-141 |
| vma/deploy/terraform.py              |      244 |       14 |     94% |76-77, 125-126, 128, 202-204, 208, 264, 285-286, 307, 355 |
| vma/deploy/variables.py              |       76 |        5 |     93% |47, 68-69, 100, 121 |
| vma/errors.py                        |        7 |        0 |    100% |           |
| vma/platform.py                      |       60 |        5 |     92% | 55, 68-71 |
| vma/secrets.py                       |       57 |        1 |     98% |        95 |
| vma/security/\_\_init\_\_.py         |       22 |        0 |    100% |           |
| vma/security/oidc.py                 |      177 |       25 |     86% |66, 113, 115, 128, 134-135, 137, 174-175, 178-179, 204, 210-221, 245 |
| vma/security/passwords.py            |       34 |        2 |     94% |    50, 52 |
| vma/security/posture.py              |       60 |        4 |     93% |28-29, 143, 145 |
| vma/security/ratelimit.py            |       66 |        6 |     91% |57, 61-64, 71 |
| vma/security/retention.py            |       80 |       31 |     61% |27-28, 31-32, 64-66, 88-110, 114-118 |
| vma/security/service.py              |      561 |       40 |     93% |84-85, 105-106, 137-140, 205, 251, 283-284, 286, 300-301, 323, 349, 359, 373, 420, 426, 442, 488, 502, 519, 530, 618, 631, 635, 640, 642, 653, 657, 665, 681, 691, 695, 711, 732, 756 |
| vma/security/store.py                |      195 |       12 |     94% |146-147, 264, 272, 313-314, 330-332, 456-458 |
| vma/settings.py                      |      112 |       37 |     67% |114-115, 119, 132-134, 138-139, 141, 150-169, 178-179, 185-190 |
| **TOTAL**                            | **11040** | **1876** | **83%** |           |

2 empty files skipped.


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/blacksoxx/vmware-migration-agent/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/blacksoxx/vmware-migration-agent/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/blacksoxx/vmware-migration-agent/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/blacksoxx/vmware-migration-agent/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fblacksoxx%2Fvmware-migration-agent%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/blacksoxx/vmware-migration-agent/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.