from __future__ import annotations

from dataclasses import dataclass

from .models import IssueCategory


@dataclass(frozen=True)
class FactRequirement:
    code: str
    question: str
    reason: str


ISSUE_KEYWORDS: dict[IssueCategory, tuple[str, ...]] = {
    IssueCategory.WAGES: (
        "工資",
        "薪水",
        "薪酬",
        "報酬",
        "金錢",
        "欠薪",
        "未付款",
        "沒有給錢",
        "不給錢",
        "支付",
        "扣款",
        "出糧",
        "salário",
    ),
    IssueCategory.WORKING_TIME: ("工作時間", "工時", "超時", "加班", "休息時間", "horas"),
    IssueCategory.WEEKLY_REST: ("每週休息", "周休", "週休", "休息日", "descanso"),
    IssueCategory.MANDATORY_HOLIDAY: ("強制性假日", "強制假日", "法定假日", "feriado"),
    IssueCategory.ANNUAL_LEAVE: ("年假", "有薪年假", "férias"),
    IssueCategory.SICK_LEAVE: ("病假", "疾病假", "doença"),
    IssueCategory.PROBATION: ("試用期", "periodo experimental"),
    IssueCategory.CONTRACT: (
        "勞動合同",
        "合同",
        "合約",
        "口頭",
        "沒有簽",
        "未簽",
        "工作條件",
        "contrato",
    ),
    IssueCategory.TERMINATION: (
        "解僱",
        "即時解僱",
        "終止合同",
        "離職",
        "通知期",
        "補償",
        "despedimento",
    ),
    IssueCategory.WORK_ACCIDENT: ("工作意外", "工傷", "職業安全", "acidente"),
    IssueCategory.OCCUPATIONAL_DISEASE: ("職業病", "doença profissional"),
    IssueCategory.FOREIGN_EMPLOYEE: ("外地僱員", "外僱", "藍卡", "工作許可", "trabalhador não residente"),
    IssueCategory.MATERNITY: ("懷孕", "產假", "生育", "maternidade"),
    IssueCategory.DISCRIMINATION: ("歧視", "差別待遇", "discriminação"),
    IssueCategory.MINOR: ("未成年", "童工", "minor"),
    IssueCategory.COLLECTIVE: ("工會", "集體談判", "罷工", "sindicato"),
    IssueCategory.CRIMINAL: ("刑事", "報警", "犯罪", "crime"),
}


GENERIC_REQUIREMENTS = (
    FactRequirement(
        code="work_location",
        question="工作地點是否在澳門特別行政區？",
        reason="系統只處理澳門法域。",
    ),
    FactRequirement(
        code="event_date",
        question="請提供事件或爭議日期，格式為 YYYY-MM-DD。",
        reason="需要按事件日期選擇當時有效的來源版本。",
    ),
)


ISSUE_REQUIREMENTS: dict[IssueCategory, tuple[FactRequirement, ...]] = {
    IssueCategory.WORKING_TIME: (
        FactRequirement(
            code="work_schedule",
            question="你實際的每日或每週工作安排是甚麼？",
            reason="需要核對實際工時安排。",
        ),
    ),
    IssueCategory.TERMINATION: (
        FactRequirement(
            code="termination_type",
            question="關係是解僱、辭職、合同到期，還是其他方式終止？",
            reason="不同終止方式需要不同事實。",
        ),
    ),
    IssueCategory.WORK_ACCIDENT: (
        FactRequirement(
            code="injury_status",
            question="是否已就醫，並是否已向僱主或官方機構申報？",
            reason="需要判斷即時安全與程序風險。",
        ),
    ),
    IssueCategory.FOREIGN_EMPLOYEE: (
        FactRequirement(
            code="foreign_employee_status",
            question="你目前是否持有有效外地僱員工作許可？",
            reason="工作許可與居留事宜需要真人處理。",
        ),
    ),
}


HIGH_RISK_CATEGORIES = {
    IssueCategory.TERMINATION,
    IssueCategory.WORK_ACCIDENT,
    IssueCategory.OCCUPATIONAL_DISEASE,
    IssueCategory.FOREIGN_EMPLOYEE,
    IssueCategory.MATERNITY,
    IssueCategory.DISCRIMINATION,
    IssueCategory.MINOR,
    IssueCategory.COLLECTIVE,
    IssueCategory.CRIMINAL,
}


HIGH_RISK_KEYWORDS = (
    "重大補償",
    "人身安全",
    "自殺",
    "威脅",
    "暴力",
    "工傷",
    "死亡",
)


GUARANTEE_KEYWORDS = (
    "保證勝訴",
    "保證一定贏",
    "一定可以告贏",
    "保證結果",
)


PROHIBITED_KEYWORDS = (
    "隱藏證據",
    "銷毀證據",
    "刪除證據",
    "偽造文件",
    "造假",
    "說謊",
    "規避法定義務",
    "逃避法律",
    "報復",
    "私下報復",
)


NON_MO_KEYWORDS = (
    "台灣",
    "台北",
    "香港",
    "中國內地",
    "大陸",
    "葡萄牙",
)


MO_KEYWORDS = ("澳門", "澳门", "macau", "macao")


ISSUE_QUERY_TEMPLATE: dict[IssueCategory, str] = {
    IssueCategory.WAGES: "工資 支付 期限 扣款",
    IssueCategory.WORKING_TIME: "正常工作時間 超時工作 休息時間",
    IssueCategory.WEEKLY_REST: "每週休息日 休息時間",
    IssueCategory.MANDATORY_HOLIDAY: "強制性假日 假日工作",
    IssueCategory.ANNUAL_LEAVE: "年假 有薪年假",
    IssueCategory.SICK_LEAVE: "病假 疾病",
    IssueCategory.PROBATION: "試用期 勞動合同",
    IssueCategory.CONTRACT: "勞動合同 合同訂立 合同形式 口頭方式 報酬",
    IssueCategory.TERMINATION: "終止合同 解僱 通知期 補償",
    IssueCategory.WORK_ACCIDENT: "工作意外 職業安全",
    IssueCategory.OCCUPATIONAL_DISEASE: "職業病 工作意外",
    IssueCategory.FOREIGN_EMPLOYEE: "外地僱員 工作許可 勞動合同",
    IssueCategory.MATERNITY: "產假 懷孕 僱員保障",
    IssueCategory.DISCRIMINATION: "歧視 平等 僱員",
    IssueCategory.MINOR: "未成年 僱員 保護",
    IssueCategory.COLLECTIVE: "工會 集體爭議",
    IssueCategory.CRIMINAL: "刑事 工作相關",
    IssueCategory.OTHER: "澳門 勞動關係",
}
