# Repository Coverage



| Name                                          |    Stmts |     Miss |   Cover |   Missing |
|---------------------------------------------- | -------: | -------: | ------: | --------: |
| hopshift/\_\_init\_\_.py                      |        1 |        1 |      0% |         8 |
| hopshift/api/app.py                           |       68 |        7 |     90% |44-46, 83, 87, 104, 113 |
| hopshift/api/deps.py                          |       44 |        1 |     98% |        61 |
| hopshift/api/middleware.py                    |       58 |        8 |     86% |84, 86, 91-96 |
| hopshift/api/routes/\_\_init\_\_.py           |       17 |        4 |     76% |     26-29 |
| hopshift/api/routes/assess.py                 |       20 |        0 |    100% |           |
| hopshift/api/routes/audit.py                  |       22 |        0 |    100% |           |
| hopshift/api/routes/auth.py                   |      115 |        1 |     99% |       115 |
| hopshift/api/routes/connections.py            |       59 |        1 |     98% |        41 |
| hopshift/api/routes/deploy.py                 |       71 |        1 |     99% |        96 |
| hopshift/api/routes/meta.py                   |       21 |        1 |     95% |        46 |
| hopshift/api/routes/runs.py                   |      243 |       78 |     68% |105, 107, 109, 111, 120-136, 189-198, 210, 221-226, 241-243, 251-255, 297, 310-316, 330-348, 353-361 |
| hopshift/api/routes/settings.py               |       36 |       15 |     58% |22, 37-46, 55, 59-64 |
| hopshift/api/routes/users.py                  |       41 |        0 |    100% |           |
| hopshift/api/serialization.py                 |       13 |        2 |     85% |    11, 17 |
| hopshift/cim/blockers.py                      |       40 |       13 |     68% |7-73, 79, 117 |
| hopshift/cim/schema.py                        |      158 |      148 |      6% |15-33, 36, 39-40, 44-136, 140-152, 156-187, 191-249, 251-256, 259-260 |
| hopshift/cim/schema\_export.py                |       29 |       13 |     55% |27, 31-41, 45 |
| hopshift/cim/vmware\_translator.py            |        2 |        0 |    100% |           |
| hopshift/cli/main.py                          |      521 |      131 |     75% |157-158, 162-167, 178-180, 195, 234-270, 286-296, 315-348, 388, 394, 410, 445, 452, 468, 476, 497-498, 520, 524, 545-554, 558-583, 589, 594-597, 601-609, 614, 651, 686, 703, 716-717, 719-720, 768, 797, 896-897, 964, 982-983, 986, 999, 1008, 1012 |
| hopshift/pipeline/config\_loader.py           |      155 |       60 |     61% |32, 36-37, 40, 44, 49, 64, 70, 76, 98-100, 119, 123, 128, 131, 134, 144, 150, 155, 161, 163, 167, 173, 175, 185, 190-204, 208-212, 227, 229, 231-234, 239-250 |
| hopshift/pipeline/generation/deterministic.py |       86 |       27 |     69% |1-30, 64, 72, 78, 86, 93, 102, 111-116, 136, 140-141, 145, 149, 153, 155 |
| hopshift/pipeline/graph.py                    |       54 |        0 |    100% |           |
| hopshift/pipeline/llm\_client.py              |      395 |      238 |     40% |1-71, 81, 89-100, 129, 159-163, 171-172, 178, 181, 192, 215-223, 238-243, 247, 263, 275-280, 311, 344, 347, 364-475, 480-511, 530, 533-536, 540-542, 546, 569, 574-584, 593, 597-661, 669, 695, 700-707, 714, 718-721, 729, 732, 736, 738-740, 744, 747, 751-754, 758, 763-767 |
| hopshift/pipeline/nodes/assess\_reporter.py   |       72 |        6 |     92% |25, 29, 71-81, 168 |
| hopshift/pipeline/nodes/blocker\_parser.py    |       61 |       16 |     74% |1-13, 19, 23, 33, 74, 77, 81, 85, 96, 100 |
| hopshift/pipeline/nodes/cim\_mapper.py        |       22 |        8 |     64% |1-11, 17, 21 |
| hopshift/pipeline/nodes/enricher.py           |      131 |       48 |     63% |1-10, 16, 20, 29, 48, 54-57, 84, 86, 88, 93, 95, 108, 110, 115, 131, 133, 138, 153, 156-163, 165, 168-179, 181, 185-191 |
| hopshift/pipeline/nodes/hcl\_generator.py     |      825 |      231 |     72% |1-33, 39, 64, 75-76, 103, 142-146, 218-268, 288-295, 333, 340, 382, 387, 397, 403, 414, 421, 437-453, 477-480, 509, 517-522, 530, 547-561, 577, 588-589, 592, 597, 605, 609, 612, 619-620, 623-624, 629-632, 639, 644-648, 652, 655, 659, 661-664, 668, 675, 678, 698, 706, 713, 716, 724, 739, 744, 749-783, 800, 807-812, 815, 819-847, 856, 864-865, 869, 913, 942-947, 952, 963, 972-973, 995, 1001, 1010, 1186, 1208, 1210, 1212, 1316, 1343, 1351, 1365, 1384, 1393, 1401, 1414, 1429, 1447, 1461, 1472, 1479, 1486, 1491-1492, 1497, 1556, 1579, 1594-1595, 1603-1604, 1616, 1620, 1641, 1646, 1683, 1687, 1695, 1697, 1702, 1723, 1739, 1824, 1837, 1850-1852, 1857-1860, 1865 |
| hopshift/pipeline/nodes/ingest.py             |       78 |       42 |     46% |1-12, 21-23, 38-65, 73, 81, 88-89, 95, 100, 108, 115, 120-126, 128 |
| hopshift/pipeline/nodes/mcp\_client.py        |      451 |      232 |     49% |98-99, 102-122, 131, 143-153, 156-189, 192-193, 196-200, 203-230, 233-262, 265-285, 288-295, 298-299, 302-306, 309-325, 334-340, 349, 375, 420, 438-439, 442-447, 451-452, 460, 492-493, 501, 508, 512, 525, 562, 571, 579, 588-636, 640-647, 660-670, 675-676, 684-699, 705, 724, 730, 747, 757, 764, 770, 773-780, 787-793, 797-800, 804-822, 826-837, 841-848 |
| hopshift/pipeline/nodes/reporter.py           |      173 |       25 |     86% |28, 149-152, 191-199, 204, 217, 229, 244, 250, 261, 290, 305-309 |
| hopshift/pipeline/nodes/risk\_assessor.py     |      248 |       67 |     73% |17, 21, 74-75, 78-79, 82-83, 86-87, 90-92, 100-101, 139-151, 160-161, 164-165, 168-169, 172-174, 182-184, 212-224, 233-234, 237-239, 242-243, 272-273, 276-278, 300-301, 304-306, 334-335, 366, 370, 381-382, 390-392, 395-397, 400-402, 426, 432, 435, 468 |
| hopshift/pipeline/nodes/sizer.py              |       45 |       15 |     67% |1-14, 20, 24, 59, 63, 66-67, 79 |
| hopshift/pipeline/nodes/validator.py          |      165 |       18 |     89% |71, 80-85, 136, 200, 214, 239-240, 275, 300, 322, 328, 337-341 |
| hopshift/pipeline/prompts.py                  |       34 |       16 |     53% |1-32, 41, 107-135, 152, 157-164, 172 |
| hopshift/pipeline/runtime.py                  |      497 |       79 |     84% |94, 96, 98, 103, 144-145, 152-153, 161, 165-166, 180-182, 233-235, 257-260, 265-267, 273, 282-283, 294, 302-304, 310, 321, 398, 412, 415, 426, 434-448, 458-468, 474, 479-480, 523-524, 552, 575, 589-591, 638, 693, 720-722, 732, 752 |
| hopshift/services/\_\_init\_\_.py             |        1 |        0 |    100% |           |
| hopshift/services/audit.py                    |      103 |        1 |     99% |       175 |
| hopshift/services/compliance/\_\_init\_\_.py  |        3 |        0 |    100% |           |
| hopshift/services/compliance/controls.py      |       34 |        1 |     97% |        48 |
| hopshift/services/compliance/report.py        |      112 |        3 |     97% |48, 93, 226 |
| hopshift/services/connections/\_\_init\_\_.py |        8 |        0 |    100% |           |
| hopshift/services/connections/aws.py          |      179 |       47 |     74% |32, 42-51, 62-65, 69-73, 83-84, 88-91, 95-96, 100-106, 113-115, 119-121, 158-159, 161, 191, 223, 239 |
| hopshift/services/connections/azure.py        |      168 |       29 |     83% |43, 53-56, 64, 117, 134-135, 140, 142-145, 153, 164-171, 217, 237-238, 240-241, 244 |
| hopshift/services/connections/gcp.py          |       87 |       25 |     71% |26, 38-44, 59-63, 68-71, 75-81, 111, 115, 122-123 |
| hopshift/services/connections/models.py       |      248 |       22 |     91% |68, 76, 128, 210-211, 223, 257, 486, 503, 507-514, 516-517, 520, 525-526 |
| hopshift/services/connections/openstack.py    |      110 |       25 |     77% |30-36, 48, 55-56, 83, 85-88, 92, 97, 105-106, 111-117, 165 |
| hopshift/services/connections/proxmox.py      |       70 |        4 |     94% |33, 50, 59, 120 |
| hopshift/services/connections/service.py      |      307 |       23 |     93% |112, 114, 126, 188-189, 223-224, 248-252, 268-269, 299, 313, 315, 350-351, 372-373, 375, 386-387 |
| hopshift/services/connections/store.py        |      109 |       13 |     88% |79-80, 119-120, 136-137, 139, 160, 171, 202, 207-209 |
| hopshift/services/db.py                       |       72 |        4 |     94% | 33, 65-67 |
| hopshift/services/deploy/\_\_init\_\_.py      |        9 |        0 |    100% |           |
| hopshift/services/deploy/service.py           |      404 |       36 |     91% |138, 140, 175, 192-193, 223, 279, 319, 321-322, 334-337, 371, 381, 391, 404, 406, 409-410, 428-429, 466, 520, 532, 535-538, 549-550, 569, 575-576, 595 |
| hopshift/services/deploy/store.py             |       85 |        3 |     96% |104, 140-141 |
| hopshift/services/deploy/terraform.py         |      244 |       14 |     94% |76-77, 125-126, 128, 202-204, 208, 264, 285-286, 307, 355 |
| hopshift/services/deploy/variables.py         |       76 |        5 |     93% |47, 68-69, 100, 121 |
| hopshift/services/errors.py                   |        7 |        0 |    100% |           |
| hopshift/services/platform.py                 |       60 |        5 |     92% | 55, 68-71 |
| hopshift/services/secrets.py                  |       57 |        1 |     98% |        95 |
| hopshift/services/security/\_\_init\_\_.py    |       22 |        0 |    100% |           |
| hopshift/services/security/oidc.py            |      177 |       25 |     86% |66, 113, 115, 128, 134-135, 137, 174-175, 178-179, 204, 210-221, 245 |
| hopshift/services/security/passwords.py       |       34 |        2 |     94% |    50, 52 |
| hopshift/services/security/posture.py         |       60 |        4 |     93% |28-29, 143, 145 |
| hopshift/services/security/ratelimit.py       |       66 |        6 |     91% |57, 61-64, 71 |
| hopshift/services/security/retention.py       |       80 |       31 |     61% |27-28, 31-32, 64-66, 88-110, 114-118 |
| hopshift/services/security/service.py         |      561 |       40 |     93% |84-85, 105-106, 137-140, 205, 251, 283-284, 286, 300-301, 323, 349, 359, 373, 420, 426, 442, 488, 502, 519, 530, 618, 631, 635, 640, 642, 653, 657, 665, 681, 691, 695, 711, 732, 756 |
| hopshift/services/security/store.py           |      195 |       12 |     94% |146-147, 264, 272, 313-314, 330-332, 456-458 |
| hopshift/services/settings.py                 |      112 |       37 |     67% |114-115, 119, 132-134, 138-139, 141, 150-169, 178-179, 185-190 |
| hopshift/sources/\_\_init\_\_.py              |       26 |       13 |     50% |7-22, 26, 39, 45-47 |
| hopshift/sources/registry.py                  |       83 |       56 |     33% |8-38, 40, 42, 44-46, 53-73, 81-89, 93, 101, 109, 114, 119 |
| hopshift/sources/vmware.py                    |      231 |       53 |     77% |7-41, 69, 95, 134, 142, 149, 152-157, 165-168, 177, 184, 188, 196, 208, 218-220, 224, 227, 240, 246, 275, 280-283, 291, 295, 310, 318, 331, 334, 360, 387, 392, 411, 415, 422, 424, 428, 430 |
| hopshift/targets/\_\_init\_\_.py              |        7 |        7 |      0% |      2-22 |
| hopshift/targets/aws/compute.py               |       71 |        2 |     97% |  107, 109 |
| hopshift/targets/aws/network.py               |      101 |       21 |     79% |13, 80, 102-115, 160, 162, 170, 177, 181 |
| hopshift/targets/aws/placement.py             |       50 |        4 |     92% |46, 58, 69, 71 |
| hopshift/targets/aws/runtime.py               |       11 |        0 |    100% |           |
| hopshift/targets/aws/sizing\_table.py         |       23 |        2 |     91% |    37, 39 |
| hopshift/targets/aws/storage.py               |       76 |        5 |     93% |64, 67, 98, 131, 133 |
| hopshift/targets/azure/compute.py             |      113 |        4 |     96% |128, 144, 152, 154 |
| hopshift/targets/azure/network.py             |      133 |       23 |     83% |13, 74-81, 84-90, 129, 134, 152, 154, 162, 169, 173 |
| hopshift/targets/azure/placement.py           |       57 |        4 |     93% |58, 70, 81, 83 |
| hopshift/targets/azure/runtime.py             |       11 |        0 |    100% |           |
| hopshift/targets/azure/sizing\_table.py       |       23 |        2 |     91% |    37, 39 |
| hopshift/targets/azure/storage.py             |       74 |        7 |     91% |30-31, 72, 75, 104, 118, 120 |
| hopshift/targets/base.py                      |       31 |       31 |      0% |      1-52 |
| hopshift/targets/common.py                    |       46 |       15 |     67% |1-9, 24-27, 32, 45, 52, 73-78 |
| hopshift/targets/gcp/compute.py               |      127 |       10 |     92% |112, 132, 140, 142, 153, 155, 165, 167, 170, 179 |
| hopshift/targets/gcp/network.py               |      145 |       33 |     77% |13, 69-80, 83-93, 116, 155, 157, 168, 170, 180, 182, 197, 201 |
| hopshift/targets/gcp/placement.py             |       48 |        6 |     88% |29, 48, 56, 58, 66, 68 |
| hopshift/targets/gcp/runtime.py               |       11 |        0 |    100% |           |
| hopshift/targets/gcp/sizing\_table.py         |       23 |        2 |     91% |    37, 39 |
| hopshift/targets/gcp/storage.py               |      105 |       14 |     87% |30-31, 76-77, 80-81, 106, 108, 125, 139, 141, 158, 160, 169 |
| hopshift/targets/openstack/compute.py         |       92 |        7 |     92% |89, 130, 136-138, 148, 150 |
| hopshift/targets/openstack/network.py         |      132 |       14 |     89% |87-95, 124, 160, 162, 170, 174 |
| hopshift/targets/openstack/placement.py       |       34 |        3 |     91% |38, 46, 48 |
| hopshift/targets/openstack/runtime.py         |       11 |        0 |    100% |           |
| hopshift/targets/openstack/sizing\_table.py   |       23 |        2 |     91% |    37, 39 |
| hopshift/targets/openstack/storage.py         |       69 |        5 |     93% |64, 67, 94, 113, 115 |
| hopshift/targets/proxmox/\_\_init\_\_.py      |      105 |        6 |     94% |60, 62, 87, 161, 177, 192 |
| hopshift/targets/proxmox/compute.py           |      164 |        3 |     98% |191-192, 227 |
| hopshift/targets/proxmox/network.py           |       47 |        0 |    100% |           |
| hopshift/targets/proxmox/placement.py         |       66 |        1 |     98% |        91 |
| hopshift/targets/proxmox/runtime.py           |       26 |        0 |    100% |           |
| hopshift/targets/proxmox/sizing\_table.py     |       11 |        0 |    100% |           |
| hopshift/targets/proxmox/storage.py           |       62 |        1 |     98% |        93 |
| hopshift/targets/registry.py                  |       83 |       58 |     30% |15-42, 44, 46-49, 53-56, 64-81, 90-98, 102, 111, 116, 121, 127-134 |
| hopshift/targets/runtime\_common.py           |       40 |        5 |     88% |20, 49, 61, 65-66 |
| hopshift/testing/\_\_init\_\_.py              |        5 |        5 |      0% |     17-23 |
| hopshift/testing/\_common.py                  |       85 |       39 |     54% |3-36, 45, 52, 64, 72, 76, 87, 95, 108, 113, 117, 122-126, 130 |
| hopshift/testing/matrix.py                    |      161 |        7 |     96% |52, 70-71, 74, 96-97, 141 |
| hopshift/testing/pytest\_plugin.py            |       33 |       15 |     55% |19-31, 35-36, 44-45, 68-69, 78 |
| hopshift/testing/report.py                    |       75 |       37 |     51% |2-22, 26-37, 42, 45, 48, 51, 73-74, 77-78, 81-82, 85-86, 89, 92, 95, 98, 112, 123 |
| hopshift/testing/sources.py                   |      166 |       52 |     69% |18-38, 57-59, 65-66, 71-75, 88, 103, 106, 108, 110, 112, 116-117, 122, 130, 149, 161, 170, 180, 188, 196, 204, 209, 211, 215, 220, 227, 229, 234, 240, 246 |
| hopshift/testing/targets.py                   |      322 |       95 |     70% |16-82, 133-134, 151, 167, 170, 172, 174, 176, 178, 183, 191, 204, 210, 231, 244, 253, 279, 306-307, 327, 338, 346, 353-355, 357, 359, 361, 364, 369, 372, 376, 378, 383, 397, 406-408, 411, 414, 418, 422, 429, 435, 451, 459, 466, 468, 477, 494, 512-538 |
| hopshift/validation/hcl\_parser.py            |       72 |       33 |     54% |9-20, 36, 39-41, 49-51, 74, 89-93, 103, 107, 110-113, 115, 119, 123, 125-129, 133-135 |
| hopshift/validation/opa\_client.py            |      172 |       69 |     60% |1-18, 30-48, 51-52, 56-59, 72, 77, 81-82, 107-108, 112-114, 119, 123-124, 139-141, 145-147, 153, 190-197, 202, 211-218, 231, 244, 248, 279, 295, 304, 314-315 |
| hopshift/validation/paths.py                  |       19 |        7 |     63% |  1-13, 30 |
| hopshift/validation/tf\_runner.py             |       94 |       52 |     45% |1-34, 38, 52, 76-82, 90-91, 107-108, 122, 131, 141, 151, 158-163, 167-191 |
| **TOTAL**                                     | **12726** | **2801** | **78%** |           |

1 empty file skipped.


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://github.com/blacksoxx/hopshift/raw/python-coverage-comment-action-data/badge.svg)](https://github.com/blacksoxx/hopshift/tree/python-coverage-comment-action-data)

This is the one to use if your repository is private or if you don't want to customize anything.



## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.