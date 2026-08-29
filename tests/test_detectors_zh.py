"""Chinese detection rules."""

from __future__ import annotations

import pytest

from mamori.infrastructure.detectors.locales.zh import resident_id_valid

from .helpers import types_in, values_of

LOCALE = "zh"

#: Invented, but with correct ISO 7064 MOD 11-2 check characters, because the
#: rule refuses anything else.
VALID_RESIDENT_IDS = ("11010519491231002X", "440524188001010014")


def zh_types(text: str) -> set[str]:
    return types_in(text, LOCALE)


def zh_values(text: str, type_name: str) -> set[str]:
    return values_of(text, type_name, LOCALE)


class TestResidentIdValidation:
    @pytest.mark.parametrize("number", VALID_RESIDENT_IDS)
    def test_accepts_a_correct_check_character(self, number: str) -> None:
        assert resident_id_valid(number)

    def test_lowercase_x_is_accepted(self) -> None:
        assert resident_id_valid("11010519491231002x")

    def test_rejects_a_wrong_check_character(self) -> None:
        assert not resident_id_valid("110105194912310021")

    @pytest.mark.parametrize("value", ["1101051949123100", "11010519491231002XY", "abc"])
    def test_rejects_wrong_shapes(self, value: str) -> None:
        assert not resident_id_valid(value)

    def test_the_rule_needs_the_checksum_to_fire(self) -> None:
        assert "RESIDENT_ID" not in zh_types("订单号 110105194912310021")

    @pytest.mark.parametrize("number", VALID_RESIDENT_IDS)
    def test_the_rule_finds_a_valid_number(self, number: str) -> None:
        assert zh_values(f"身份证号 {number}", "RESIDENT_ID") == {number}


class TestContactDetails:
    def test_mainland_mobile_number(self) -> None:
        assert zh_values("请拨打 13812345678", "PHONE") == {"13812345678"}

    def test_landline_needs_a_separator(self) -> None:
        assert "PHONE" in zh_types("电话 010-12345678")

    def test_a_bare_digit_run_is_not_a_phone_number(self) -> None:
        assert "PHONE" not in zh_types("订单号 23812345678")

    def test_postcode_needs_its_label(self) -> None:
        assert zh_values("邮编 100081", "POSTAL_CODE") == {"100081"}
        assert "POSTAL_CODE" not in zh_types("编号 100081")

    def test_date_of_birth_needs_its_label(self) -> None:
        assert zh_values("出生日期: 1985-04-01", "DATE_OF_BIRTH") == {"1985-04-01"}
        assert "DATE_OF_BIRTH" not in zh_types("交货日期是 1985-04-01")

    def test_address(self) -> None:
        assert "ADDRESS" in zh_types("北京市海淀区中关村大街1号")


class TestOrganisations:
    @pytest.mark.parametrize("company", ["北京云图科技有限公司", "云图股份有限公司", "云图集团"])
    def test_company_suffixes(self, company: str) -> None:
        assert company in zh_values(f"合作方是{company}", "COMPANY_NAME")

    def test_a_company_name_stops_at_a_particle(self) -> None:
        """A greedy run of Han characters would swallow the rest of the sentence."""
        assert zh_values("这是北京云图科技有限公司的张伟", "COMPANY_NAME") == {
            "北京云图科技有限公司"
        }

    def test_the_label_may_be_separated_from_its_value(self) -> None:
        """工号预留为 X. The label is rarely flush against the number.

        Same shape as the Japanese 社員番号は fix in 0.14, found the same way
        and missed twenty-eight times in a thousand generated documents.
        """
        assert zh_values("若入职，工号预留为E-52260。", "EMPLOYEE_ID") == {"E-52260"}

    def test_the_gap_may_not_cross_a_clause(self) -> None:
        assert "EMPLOYEE_ID" not in zh_types("工号未定，联系电话为010-12345678")

    def test_employee_id_needs_its_label(self) -> None:
        assert zh_values("工号: A-12345", "EMPLOYEE_ID") == {"A-12345"}

    def test_project_code_needs_its_label(self) -> None:
        assert zh_values("项目名称: 夜莺", "PROJECT_NAME") == {"夜莺"}


class TestPersonNames:
    def test_honorific_anchored(self) -> None:
        assert "张伟" in zh_values("张伟先生您好", "PERSON")

    def test_the_honorific_is_not_part_of_the_value(self) -> None:
        assert all("先生" not in value for value in zh_values("张伟先生您好", "PERSON"))

    def test_title_as_honorific(self) -> None:
        assert "李明" in zh_values("请联系李明经理", "PERSON")

    def test_dictionary_anchored_full_name(self) -> None:
        assert "张伟" in zh_values("负责人是张伟，谢谢", "PERSON")

    def test_compound_surname(self) -> None:
        assert "欧阳修" in zh_values("作者是欧阳修，宋代人", "PERSON")

    def test_polite_address_is_not_a_person(self) -> None:
        assert "PERSON" not in zh_types("各位女士，欢迎")

    def test_a_company_is_not_read_as_a_person(self) -> None:
        assert "PERSON" not in zh_types("发给王氏集团")

    def test_a_place_is_not_read_as_a_person(self) -> None:
        assert "PERSON" not in zh_types("我去江苏省")


class TestANameRunsIntoTheNextWord:
    """0.15. Chinese has no spaces and the rules used to require one anyway.

    Every case here matched nothing at all before, because the name had to
    end at a non-Han character. A thousand generated documents missed 104
    names this way, which is the largest single gap the project has measured.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "张伟汇报了进度。",
            "李明的报告已经收到",
            "王强负责办理设备",
            "由徐乐山医生接诊",
        ],
    )
    def test_a_name_followed_by_a_han_character(self, text: str) -> None:
        assert "PERSON" in zh_types(text)

    def test_a_given_name_may_end_in_a_mountain(self) -> None:
        """山, 江 and 河 end places, and they end given names too."""
        assert "PERSON" in zh_types("由孙乐山负责")

    def test_but_a_place_suffix_still_wins(self) -> None:
        assert "PERSON" not in zh_types("我去江苏省")
        assert "PERSON" not in zh_types("寄到王家村")

    @pytest.mark.parametrize("text", ["关于上次讨论", "手册仍然指向旧地址", "向管委会汇报"])
    def test_a_preposition_is_not_a_name(self, text: str) -> None:
        """于 and 向 are surnames. They are also the commonest words here."""
        assert "PERSON" not in zh_types(text)

    def test_the_relaxed_edge_still_refuses_an_organisation(self) -> None:
        assert "PERSON" not in zh_types("发给王氏集团办理")


class TestUniversalRulesStillApply:
    def test_email(self) -> None:
        assert zh_values("邮箱是 zhang@example.com", "EMAIL") == {"zhang@example.com"}

    def test_password_assignment_in_chinese(self) -> None:
        assert zh_values("密码: hunter2xyz", "PASSWORD") == {"hunter2xyz"}
