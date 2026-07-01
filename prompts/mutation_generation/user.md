请基于相似测试做最小变异，生成 1 个 BRT。

实例：{instance_id}
测试函数名必须是：test_brt_{safe_instance_id}
放置策略：必须生成一个完整的新 Python 测试文件，后续会保存到最相似测试同级目录下的 test_brt_{safe_instance_id}.py。
不要输出需要插入到已有 class 或已有文件中的 method 片段。
不要输出裸缩进代码。
如果需要 class wrapper，请在新文件中完整定义 class，并包含必要 imports。
完整文件必须能作为独立 .py 文件被 pytest/Django/Sympy 测试命令收集；不能依赖原相似测试文件里已经 import 的名字、模型、fixture helper、全局变量或 class，除非你在新文件中显式 import 或定义。
如果复用相似测试中的 TestCase、fixture、helper、model、decorator、pytestmark 或断言风格，必须把运行所需的 import/decorator/setup 一并写入新文件。
对于 Django 同目录/同测试 app 的 seed，不要为了复用基类或 helper 而通过 `from tests.<app>.tests import ...` 绝对导入整份测试模块，除非 HostContext 的 seed runner 已证明这个精确导入可执行。该导入常会在 app registry 完成前加载测试 models/admin，导致 app_label 或 INSTALLED_APPS 错误。优先在新文件内复制最小必要的类级属性、setUp、fixture 和 import；若必须导入，只导入同包中已验证且不会触发 app registry 的稳定 helper。
如果 HostContext.setup_context 包含类级属性（例如 CHECKER_CLASS、databases、app_label、配置常量），必须保留其精确名称和值，不得根据测试名称猜测替代类。
不得引入相似测试、完整宿主文件、相关源码或 Python 标准库中没有依据的第三方模块。
必须服从 HostContext 中的实际 runner：如果 runner 是 SymPy bin/test，不要默认 import pytest 或使用 pytest fixture；如果 runner 是 Django runtests，使用现有 Django TestCase 与测试应用约定。
测试的断言必须表达 expected_behavior，而不是期待 buggy error_symptom 继续发生。
完整文件只能包含一个可收集的 test 函数或 test method；不要生成 baseline、对照组、
备用候选或多个测试入口，因为评测只执行这个唯一 BRT。
不得使用 pytest.skip、skipIf、skipUnless 或平台不满足时提前 return；测试必须真实执行。
不得使用 assert True、A or not A、x == x or x != x 等恒真断言。
不得用 broad try/except 吞掉异常，不得 mock/patch 掉 target API 或 Issue 要观察的内部行为。
Issue 给出 MWE、字面输入、参数、operator、调用顺序时必须原样保留这些路径锚点；
不能为了让测试可运行而换成更简单但不触发缺陷的输入或 API。
如果缺陷是“缺少检查、缺少 warning、缺少状态更新或静默接受错误配置”，不要寻找一个
buggy 版本已经存在的异常路径。应调用项目真实的检查/验证/状态转换 API，并断言修复后
应出现的稳定证据；buggy 版本因证据缺失而自然 assertion fail。
如果缺陷是“缺少日志”，使用 assertLogs/caplog 捕获目标模块的日志命名空间；
不要 patch buggy 源码中尚不存在的 logger 属性。
只有 expected_behavior 明确要求抛异常时才使用 assertRaises/pytest.raises。
行为目标：{behavior_json}
HostContext：{host_context_json}
相关源码：{code_context}
anchor_seed 代码（唯一允许继承 host scaffold 的测试）：{seed_test_code}
上一轮反馈：{feedback}

要求：保留 anchor_seed 的可执行上下文，只修改输入值、参数、对象状态、mock、配置、调用链、边界值或 operator 中与 Issue 相关的部分。reference_seeds 只能提供 API 用法、对象构造、边界输入、断言风格或 mock pattern 参考；不要混用不兼容 fixture/class setup。不要裸 assert False。只输出 Python 代码，不要 markdown，不要解释。
