import pytest

from classify_storage_tasks import _detect_structured_math_type


@pytest.mark.parametrize(
    ("question", "expected_title"),
    [
        (
            "目前生成一辆卡车运矿石，晴天每天可运20次，雨天每天可运12次，它一共运了112次，平均每天运14次，这几天中有几天是雨天？",
            "鸡兔同笼",
        ),
        (
            "鸡和兔共有35只，数脚共有94只，鸡和兔各有多少只？",
            "鸡兔同笼",
        ),
        (
            "一列火车长180米，以每秒20米的速度通过一座长420米的大桥，需要多少秒？",
            "列车过桥过隧道问题",
        ),
        (
            "甲乙两车相向而行，甲车每小时行60千米，乙车每小时行40千米，两车相距200千米，几小时后相遇？",
            "相遇与追及问题",
        ),
        (
            "有一个自然数，用它分别去除以5、7、9，得到的余数分别是3、4、5，求这个自然数最小是多少。",
            "余数与同余问题",
        ),
        (
            "一个数除以7，商是12，余数是3，求被除数。",
            "余数与同余问题",
        ),
        (
            "一项工程，甲单独完成要10天，乙单独完成要15天，两人合作完成需要多少天？",
            "工程问题",
        ),
        (
            "一件商品进价80元，售价100元，求这件商品的利润率是多少？",
            "利润折扣问题",
        ),
        (
            "袋中有红球和黄球共50个，红球个数比黄球的3倍多2个，随机摸出一个球，求摸到黄球的概率。",
            "概率问题",
        ),
        (
            "某班学生数学成绩的平均数是82，中位数是84，众数是90，求这组数据的方差。",
            "统计图表问题",
        ),
        (
            "一个圆的半径是5厘米，求这个圆的周长和面积。",
            "圆与扇形问题",
        ),
        (
            "一个长方形长12厘米，宽8厘米，求它的面积和周长。",
            "几何面积周长问题",
        ),
        (
            "已知一次函数y=2x+3，求它与x轴的交点坐标。",
            "函数图象问题",
        ),
        (
            "解二元一次方程组：x+y=10，2x-y=5。",
            "二元一次方程组",
        ),
        (
            "解不等式2x-3大于5，并写出它的解集。",
            "不等式问题",
        ),
        (
            "在一幅比例尺为1:5000的地图上，量得两地距离是3厘米，求实际距离。",
            "比和比例问题",
        ),
        (
            "一件衣服原价200元，现在打八折出售，现价是多少元？",
            "利润折扣问题",
        ),
        (
            "一根绳子用去全长的三分之一，还剩12米，这根绳子原来长多少米？",
            "分数应用题",
        ),
        (
            "设未知数x，列方程并解答：某数的3倍减去5等于16，这个数是多少？",
            "一元一次方程应用题",
        ),
    ],
)
def test_detect_common_structured_math_types(question, expected_title):
    result = _detect_structured_math_type(question)

    assert result is not None
    assert result["is_math_problem"] is True
    assert result["title"] == expected_title
    assert result["question"] == question


def test_unstructured_math_question_falls_back_to_llm():
    question = "请证明任意三角形两边之和大于第三边。"

    result = _detect_structured_math_type(question)

    assert result is None
