"""Tests for Sprinklr-specific DOM extraction helpers."""

from __future__ import annotations

from app.dom_extractor import (
    _clean_answer_candidate_details,
    _detect_topic_family,
    _is_stale_or_invalid_candidate,
    _looks_truncated,
    _strip_ui_noise,
    _strip_followup_cta,
    _strip_meta_text,
    _strip_promo_review_blocks,
    build_post_baseline_answer_candidates,
    choose_best_answer_segment,
    compute_new_text_segments,
    extract_clean_text_from_message_node,
    filter_out_static_ui_text,
    is_static_ui_text,
    looks_like_chat_history_dump,
    normalize_text_for_diff,
)


class TestStaticUiFiltering:
    def test_static_header_is_rejected(self):
        assert is_static_ui_text("삼성닷컴 구매 상담사와 채팅하세요") is True
        assert is_static_ui_text("Samsung AI Assistant") is True

    def test_real_answer_is_not_rejected(self):
        assert is_static_ui_text("갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.") is False

    def test_filter_out_static_ui_segments(self):
        segments = [
            "Samsung AI Assistant",
            "아래에서 원하는 항목을 선택해 주세요",
            "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.",
        ]
        filtered = filter_out_static_ui_text(segments)
        assert filtered == ["갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."]

    def test_close_button_text_is_rejected(self):
        assert is_static_ui_text("닫기") is True

    def test_korean_timestamp_is_rejected(self):
        assert is_static_ui_text("\u200e오전 12:30") is True

    def test_feedback_and_timestamp_meta_is_stripped(self):
        assert _strip_meta_text("좋아요 싫어함 오전 1:43") == ""

    def test_followup_prompt_is_stripped_from_answer(self):
        text = (
            "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
            "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다. "
            "🔍 이어서 물어보세요 가까운 서비스센터에서 바로 가능한가요? "
            "배터리 교체 비용은 얼마나 나와요?"
        )
        assert _strip_meta_text(text) == (
            "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
            "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다."
        )

    def test_accessibility_prefix_is_stripped_from_answer(self):
        text = (
            "자세한 내용을 보려면 Enter를 누르세요. 리치 텍스트 메시지 "
            "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요."
        )
        assert _strip_meta_text(text) == "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요."

    def test_accessibility_prefix_with_leading_punctuation_is_stripped_from_answer(self):
        text = ", 자세한 내용을 보려면 Enter를 누르세요. 갤럭시 S26 울트라는 6.9형 디스플레이입니다."
        assert _strip_meta_text(text) == "갤럭시 S26 울트라는 6.9형 디스플레이입니다."

    def test_received_prefix_is_stripped_from_answer(self):
        text = "에 수신됨, 자세한 내용을 보려면 Enter를 누르세요. 갤럭시 링은 최대 7일 사용 가능합니다."
        assert _strip_meta_text(text) == "갤럭시 링은 최대 7일 사용 가능합니다."

    def test_strip_ui_noise_reports_when_prefix_removed(self):
        text = "에 수신됨, 자세한 내용을 보려면 Enter를 누르세요. 갤럭시 버즈3 프로는 ANC를 지원합니다."
        cleaned, stripped = _strip_ui_noise(text)
        assert cleaned == "갤럭시 버즈3 프로는 ANC를 지원합니다."
        assert stripped is True

    def test_loading_prefix_is_stripped_from_answer(self):
        text = "답변 생성 중 갤럭시 링 정보를 확인하고 있어요. 갤럭시 링은 최대 7일 사용 가능합니다."
        assert _strip_meta_text(text) == "갤럭시 링은 최대 7일 사용 가능합니다."

    def test_product_card_tail_is_stripped_from_answer(self):
        text = (
            "갤럭시 S24는 6.2형 디스플레이와 4,000mAh 배터리를 제공합니다. "
            "갤럭시 S24 자급제 (SM-S921N) ⭐ 4.8 1,155,000원 44,000원 할인 더 알아보기"
        )
        assert _strip_meta_text(text) == "갤럭시 S24는 6.2형 디스플레이와 4,000mAh 배터리를 제공합니다."

    def test_strip_followup_cta_removes_followup_block(self):
        text = "배터리 5000mAh입니다. 더 알아보기\n추천 질문: 카메라는 어떤가요?\nCS AI 챗봇에 문의해 주세요."
        cleaned, stripped = _strip_followup_cta(text)
        assert cleaned == "배터리 5000mAh입니다."
        assert stripped is True

    def test_strip_promo_review_blocks_removes_review_and_benefit(self):
        text = "무게는 1.69kg입니다.\n리뷰 한줄 요약: 휴대성이 좋습니다.\n구매 혜택: 할인 7%"
        cleaned, stripped = _strip_promo_review_blocks(text, question="갤럭시 북5 프로 360 무게 알려줘")
        assert cleaned == "무게는 1.69kg입니다."
        assert stripped is True

    def test_strip_promo_review_blocks_trims_inline_price_benefit_tail(self):
        text = (
            "카메라와 화면 기준으로 보면 울트라가 더 강력합니다. "
            "💰 지금 가격/혜택 흐름 S26 울트라: 즉시 할인 최대 6% "
            "카드사 혜택/무이자 할부"
        )
        cleaned, stripped = _strip_promo_review_blocks(text, question="S26 울트라와 플러스 차이 알려줘")
        assert cleaned == "카메라와 화면 기준으로 보면 울트라가 더 강력합니다."
        assert stripped is True

    def test_strip_promo_review_blocks_removes_product_card_lines(self):
        text = (
            "카메라와 화면 기준으로 보면 울트라가 더 강력합니다.\n"
            "갤럭시 S26 울트라 자급제 (SM-S948NZVBKOO)\n"
            "⭐ 4.9 (15101)\n"
            "1,693,400원\n"
            "104,000원 할인\n"
            "더 알아보기"
        )
        cleaned, stripped = _strip_promo_review_blocks(text, question="S26 울트라와 플러스 차이 알려줘")
        assert cleaned == "카메라와 화면 기준으로 보면 울트라가 더 강력합니다."
        assert stripped is True

    def test_strip_promo_review_blocks_trims_storage_option_tail(self):
        text = (
            "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다. "
            "⚠️ 저장용량 옵션이 256GB / 512GB / 1TB로 나뉘니, 촬영이 잦으면 512GB 이상이 선택이 편해요."
        )
        cleaned, stripped = _strip_promo_review_blocks(text, question="갤럭시 S26 울트라 핵심 사양 알려줘")
        assert cleaned == "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다."
        assert stripped is True

    def test_strip_promo_review_blocks_trims_advisory_tail(self):
        text = (
            "갤럭시 버즈3 프로는 ANC와 IP57 방수를 지원합니다. "
            "다음 선택 포인트는 2가지예요. 통화 위주면 ANC 켠 통화 시간이 중요합니다."
        )
        cleaned, stripped = _strip_promo_review_blocks(text, question="갤럭시 버즈3 프로 방수와 ANC 알려줘")
        assert cleaned == "갤럭시 버즈3 프로는 ANC와 IP57 방수를 지원합니다."
        assert stripped is True

    def test_strip_promo_review_blocks_trims_inline_review_tail_variant(self):
        text = (
            "갤럭시 북5 프로 360은 16형 기준 1.69kg입니다. "
            "리뷰에서도 휴대성이 좋다는 반응이 많습니다."
        )
        cleaned, stripped = _strip_promo_review_blocks(text, question="갤럭시 북5 프로 360 무게 알려줘")
        assert cleaned == "갤럭시 북5 프로 360은 16형 기준 1.69kg입니다."
        assert stripped is True

    def test_clean_answer_candidate_details_reports_cleaning_flags(self):
        text = "배터리 5000mAh입니다. 더 알아보기\n추천 질문: 카메라는 어떤가요?\nCS AI 챗봇에 문의해 주세요."
        details = _clean_answer_candidate_details(text, question="배터리 알려줘")
        assert details["cleaned_answer"] == "배터리 5000mAh입니다."
        assert details["cta_stripped"] is True

    def test_clean_answer_candidate_details_marks_carryover_reject(self):
        details = _clean_answer_candidate_details(
            "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다.",
            question="갤럭시 버즈3 프로 방수와 ANC 알려줘",
            baseline_last_answer="갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다.",
            baseline_topic_family="phone",
        )
        assert details["carryover_detected"] is True

    def test_clean_answer_candidate_details_detects_truncated_answer(self):
        details = _clean_answer_candidate_details("운동용으로도 매칭이 .", question="버즈3 프로 방수 알려줘")
        assert details["truncated_detected"] is True
        assert details["cleaned_answer"] == ""

    def test_clean_answer_candidate_details_rejects_progress_placeholder(self):
        details = _clean_answer_candidate_details(
            "갤럭시 S26 정보를 정리하고 있어요.",
            question="갤럭시 S26 울트라 핵심 사양 알려줘",
        )
        assert details["cleaned_answer"] == ""

    def test_clean_answer_candidate_details_rejects_progress_placeholder_with_topic_nouns_only(self):
        details = _clean_answer_candidate_details(
            "갤럭시 워치 울트라와 갤럭시 워치7의 배터리·운동 기능 차이와 현재 혜택을 정리하고 있어요.",
            question="갤럭시 워치 울트라와 갤럭시 워치7 차이 알려줘",
        )
        assert details["cleaned_answer"] == ""

    def test_clean_answer_candidate_details_rejects_spaced_progress_placeholder_variant(self):
        details = _clean_answer_candidate_details(
            "OLED TV와 Neo QLED TV 제품별 특징과 혜택을 비교해 보고 있어요.",
            question="OLED TV와 Neo QLED TV 차이 알려줘",
        )
        assert details["cleaned_answer"] == ""

    def test_clean_answer_candidate_details_rejects_formal_progress_placeholder_variant(self):
        details = _clean_answer_candidate_details(
            "오디세이 OLED G8과 Neo G9의 화면 크기, 주사율, 게임 몰입감 차이를 비교할 수 있게 정보를 정리하고 있습니다.",
            question="오디세이 OLED G8과 Neo G9 차이 알려줘",
        )
        assert details["cleaned_answer"] == ""

    def test_clean_answer_candidate_details_rejects_model_checking_placeholder_variant(self):
        details = _clean_answer_candidate_details(
            "갤럭시 북5 프로 360의 모델별 무게, 배터리, 포트 구성을 확인하고 있습니다.",
            question="갤럭시 북5 프로 360의 무게와 배터리 그리고 포트 구성을 알려주세요.",
        )
        assert details["cleaned_answer"] == ""

    def test_clean_answer_candidate_details_keeps_substantive_answer_with_progress_phrase(self):
        details = _clean_answer_candidate_details(
            "비교해보고 있어요. 갤럭시 버즈3 프로는 ANC와 IP57 방수를 지원합니다.",
            question="갤럭시 버즈3 프로 방수와 ANC 알려줘",
        )
        assert details["cleaned_answer"] == "비교해보고 있어요. 갤럭시 버즈3 프로는 ANC와 IP57 방수를 지원합니다."

    def test_clean_answer_candidate_details_rejects_embedded_broken_fragment(self):
        details = _clean_answer_candidate_details(
            "비스포크 냉장고는 633~640L 키친핏 Max가 3~4인 가정에서 균형이 . 864L 모델은 대용량 보관에 적합합니다.",
            question="비스포크 냉장고 용량 추천해줘",
        )
        assert details["truncated_detected"] is True
        assert details["cleaned_answer"] == ""

    def test_looks_truncated_matches_requested_pattern(self):
        assert _looks_truncated("운동용으로도 매칭이 .") is True

    def test_looks_truncated_matches_live_tail_patterns(self):
        assert _looks_truncated("실사용으로") is True
        assert _looks_truncated("이걸로 정리되면") is True

    def test_chat_history_dump_is_detected(self):
        text = (
            "4월 9일 (목) 첨부 Samsung AI CS Chat 안녕하세요 송제혁님 "
            "삼성닷컴에서 어떤 제품들을 구매할 수 있나요? 프롬프트 생성 중 오류가 발생했습니다. "
            "채팅을 다시 시작하세요. 갤럭시 S26 울트라의 디스플레이 크기와 카메라 구성 그리고 배터리 같은 핵심 사양을 알려주세요?"
        )

        assert looks_like_chat_history_dump(text) is True


class TestDiffHelpers:
    def test_compute_new_text_segments(self):
        before = ["Samsung AI Assistant", "구매 상담사 연결"]
        after = before + ["갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."]
        segments = compute_new_text_segments(before, after)
        assert segments == ["갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."]

    def test_choose_best_answer_segment_prefers_real_answer(self):
        segments = [
            "서비스 센터",
            "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.",
            "FAQ",
        ]
        best = choose_best_answer_segment(segments)
        assert best == "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."

    def test_choose_best_answer_segment_ignores_timestamp(self):
        segments = [
            "\u200e오전 12:30",
            "주문 배송 조회는 삼성닷컴 마이페이지의 주문/배송 조회 메뉴에서 확인할 수 있습니다.",
        ]
        best = choose_best_answer_segment(segments)
        assert best == "주문 배송 조회는 삼성닷컴 마이페이지의 주문/배송 조회 메뉴에서 확인할 수 있습니다."

    def test_choose_best_answer_segment_ignores_feedback_meta(self):
        segments = [
            "좋아요 싫어함 오전 1:43",
            "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.",
        ]
        best = choose_best_answer_segment(segments)
        assert best == "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."

    def test_choose_best_answer_segment_prefers_body_over_followup_question(self):
        segments = [
            "가까운 서비스센터에서 바로 가능한가요?",
            (
                "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
                "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다."
            ),
        ]
        best = choose_best_answer_segment(segments)
        assert best == (
            "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
            "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다."
        )

    def test_choose_best_answer_segment_penalizes_product_card_snippet(self):
        segments = [
            "갤럭시 S24 자급제 (SM-S921N) ⭐ 4.8 1,155,000원 44,000원 할인 더 알아보기",
            "갤럭시 S24와 S24+의 가장 큰 차이는 화면 크기와 배터리 용량입니다.",
        ]
        best = choose_best_answer_segment(segments)
        assert best == "갤럭시 S24와 S24+의 가장 큰 차이는 화면 크기와 배터리 용량입니다."

    def test_choose_best_answer_segment_penalizes_product_title_only(self):
        segments = [
            "갤럭시 S26 울트라 자급제 (삼성닷컴/삼성 강남 전용컬러) (SM-S948NZDWKOO)",
            "카메라와 화면 그리고 S펜 기준으로 보면, S26 울트라는 줌과 S펜까지 포함된 올인원이고 S26+는 큰 화면 대비 휴대성이 더 좋습니다.",
        ]
        best = choose_best_answer_segment(segments)
        assert best == "카메라와 화면 그리고 S펜 기준으로 보면, S26 울트라는 줌과 S펜까지 포함된 올인원이고 S26+는 큰 화면 대비 휴대성이 더 좋습니다."

    def test_choose_best_answer_segment_ignores_chat_history_dump(self):
        segments = [
            (
                "4월 9일 (목) 첨부 Samsung AI CS Chat 안녕하세요 송제혁님 "
                "삼성닷컴에서 어떤 제품들을 구매할 수 있나요? 프롬프트 생성 중 오류가 발생했습니다. "
                "채팅을 다시 시작하세요. 갤럭시 S26 울트라의 디스플레이 크기와 카메라 구성 그리고 배터리 같은 핵심 사양을 알려주세요?"
            ),
            (
                "갤럭시 버즈3 프로는 배터리가 케이스 포함 최대 26시간 노캔 켜짐 기준, "
                "방수는 IP57, 오디오는 2-way 스피커와 적응형 노이즈 캔슬링이 핵심이에요."
            ),
        ]

        best = choose_best_answer_segment(segments)
        assert best == (
            "갤럭시 버즈3 프로는 배터리가 케이스 포함 최대 26시간 노캔 켜짐 기준, "
            "방수는 IP57, 오디오는 2-way 스피커와 적응형 노이즈 캔슬링이 핵심이에요."
        )

    def test_choose_best_answer_segment_rejects_question_repetition(self):
        question = "갤럭시 버즈3 프로 방수와 ANC 알려줘"
        segments = [
            question,
            "갤럭시 버즈3 프로는 IP57 방수와 적응형 노이즈 캔슬링을 지원합니다.",
        ]

        best = choose_best_answer_segment(segments, question=question)
        assert best == "갤럭시 버즈3 프로는 IP57 방수와 적응형 노이즈 캔슬링을 지원합니다."

    def test_choose_best_answer_segment_removes_promo_review_noise_when_not_asked(self):
        question = "갤럭시 버즈3 프로 ANC와 방수 알려줘"
        segments = [
            "갤럭시 버즈3 프로는 적응형 노이즈 캔슬링과 IP57 방수를 지원합니다.\n구매 혜택\n할인 쿠폰\n리뷰에서는 착용감이 좋다는 반응이 많습니다.",
        ]

        best = choose_best_answer_segment(segments, question=question)
        assert best == "갤럭시 버즈3 프로는 적응형 노이즈 캔슬링과 IP57 방수를 지원합니다."

    def test_choose_best_answer_segment_trims_price_and_promo_tail(self):
        question = "갤럭시 S26 울트라와 갤럭시 S26 플러스의 차이를 비교해 주세요"
        segments = [
            (
                "카메라·화면·S펜 기준으로 보면 울트라가 더 강력하고 플러스는 더 가볍습니다. "
                "💰 지금 가격/혜택 흐름 S26 울트라: 즉시 할인 최대 6% 카드사 혜택/무이자 할부"
            )
        ]

        best = choose_best_answer_segment(segments, question=question)
        assert best == "카메라·화면·S펜 기준으로 보면 울트라가 더 강력하고 플러스는 더 가볍습니다."

    def test_choose_best_answer_segment_trims_storage_and_advisory_tail(self):
        question = "갤럭시 S26 울트라 핵심 사양 알려줘"
        segments = [
            (
                "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다. "
                "이 사양이면 이런 분들께 특히 잘 맞아요. 큰 화면으로 영상과 게임을 많이 보는 분. "
                "⚠️ 저장용량 옵션이 256GB / 512GB / 1TB로 나뉘니 512GB 이상이 선택이 편해요."
            )
        ]

        best = choose_best_answer_segment(segments, question=question)
        assert best == "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다."


class TestTopicFamilyDetection:
    def test_detect_topic_family_prefers_earbuds_over_generic_galaxy_phone_tokens(self):
        question = "갤럭시 버즈3 프로의 배터리 시간과 방수 등급 그리고 주요 오디오 기능을 알려주세요."

        assert _detect_topic_family(question) == "earbuds"

    def test_stale_phone_answer_is_rejected_for_earbuds_question(self):
        question = "갤럭시 버즈3 프로의 배터리 시간과 방수 등급 그리고 주요 오디오 기능을 알려주세요."
        baseline_answer = "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다."
        carryover_answer = (
            "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다. "
            "200MP 카메라와 쿼드 카메라 구성이 특징입니다."
        )

        assert _is_stale_or_invalid_candidate(
            question,
            carryover_answer,
            carryover_answer,
            baseline_last_answer=baseline_answer,
            baseline_topic_family="phone",
        ) is True


class TestMessageNodeExtraction:
    def test_extract_clean_text_from_wrapper_prefers_text_child(self):
        node = {
            "wrapperText": "삼성닷컴 구매 상담사와 채팅하세요 갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.",
            "descendants": [
                {"text": "삼성닷컴 구매 상담사와 채팅하세요"},
                {"text": "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."},
            ],
        }
        assert extract_clean_text_from_message_node(node) == "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."

    def test_extract_clean_text_from_message_node_strips_followup_prompt(self):
        node = {
            "wrapperText": (
                "리치 텍스트 메시지 갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
                "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다. "
                "🔍 이어서 물어보세요 가까운 서비스센터에서 바로 가능한가요?"
            ),
            "descendants": [
                {
                    "text": (
                        "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
                        "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다."
                    )
                },
                {"text": "가까운 서비스센터에서 바로 가능한가요?"},
            ],
        }
        assert extract_clean_text_from_message_node(node) == (
            "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
            "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다."
        )

    def test_normalize_text_for_diff(self):
        assert normalize_text_for_diff("  안녕\n하세요  ") == "안녕 하세요"


class TestPostBaselineCandidates:
    def test_answer_prefers_best_new_bot_candidate(self):
        class DummyContext:
            baseline_bot_count = 1
            baseline_bot_messages = ["구매 상담사와 채팅 하세요"]
            baseline_message_nodes_snapshot = ["구매 상담사와 채팅 하세요"]

        from unittest.mock import patch

        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={
                    "history": ["구매 상담사와 채팅 하세요", "최종 답변입니다.", "가까운 서비스센터에서 바로 가능한가요?"],
                    "count": 3,
                    "fallback_diff_used": False,
                },
            ),
            patch(
                "app.dom_extractor.extract_bot_message_texts",
                return_value=["구매 상담사와 채팅 하세요", "최종 답변입니다.", "가까운 서비스센터에서 바로 가능한가요?"],
            ),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=["최종 답변입니다."]),
            patch(
                "app.dom_extractor.extract_visible_chat_text",
                return_value="구매 상담사와 채팅 하세요\n최종 답변입니다.\n가까운 서비스센터에서 바로 가능한가요?",
            ),
            patch(
                "app.dom_extractor.extract_visible_text_blocks",
                return_value=["최종 답변입니다.", "가까운 서비스센터에서 바로 가능한가요?"],
            ),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext())

        assert payload["answer"] == "최종 답변입니다."
        assert payload["strict_candidates"] == ["최종 답변입니다.", "가까운 서비스센터에서 바로 가능한가요?"]

    def test_answer_ignores_korean_timestamp_meta(self):
        class DummyContext:
            baseline_bot_count = 1
            baseline_bot_messages = ["구매 상담사와 채팅 하세요"]
            baseline_message_nodes_snapshot = ["구매 상담사와 채팅 하세요"]
            baseline_visible_blocks = ["구매 상담사와 채팅 하세요"]

        from unittest.mock import patch

        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={
                    "history": [
                        "구매 상담사와 채팅 하세요",
                        "\u200e오전 12:30",
                        "주문 배송 조회는 삼성닷컴 마이페이지에서 확인할 수 있습니다.",
                    ],
                    "count": 3,
                    "fallback_diff_used": False,
                },
            ),
            patch(
                "app.dom_extractor.extract_bot_message_texts",
                return_value=[
                    "구매 상담사와 채팅 하세요",
                    "\u200e오전 12:30",
                    "주문 배송 조회는 삼성닷컴 마이페이지에서 확인할 수 있습니다.",
                ],
            ),
            patch(
                "app.dom_extractor.diff_visible_text_against_baseline",
                return_value=["\u200e오전 12:30", "주문 배송 조회는 삼성닷컴 마이페이지에서 확인할 수 있습니다."],
            ),
            patch(
                "app.dom_extractor.extract_visible_chat_text",
                return_value="구매 상담사와 채팅 하세요\n\u200e오전 12:30\n주문 배송 조회는 삼성닷컴 마이페이지에서 확인할 수 있습니다.",
            ),
            patch(
                "app.dom_extractor.extract_visible_text_blocks",
                return_value=["\u200e오전 12:30", "주문 배송 조회는 삼성닷컴 마이페이지에서 확인할 수 있습니다."],
            ),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext())

        assert payload["answer"] == "주문 배송 조회는 삼성닷컴 마이페이지에서 확인할 수 있습니다."

    def test_stale_carryover_contamination_is_rejected(self):
        class DummyContext:
            baseline_bot_count = 1
            baseline_bot_messages = ["갤럭시 S26 울트라는 6.9형 디스플레이와 200MP 카메라를 제공합니다."]
            baseline_message_nodes_snapshot = ["갤럭시 S26 울트라는 6.9형 디스플레이와 200MP 카메라를 제공합니다."]
            baseline_visible_blocks = ["갤럭시 S26 울트라는 6.9형 디스플레이와 200MP 카메라를 제공합니다."]
            baseline_last_answer = "갤럭시 S26 울트라는 6.9형 디스플레이와 200MP 카메라를 제공합니다."
            baseline_topic_family = "phone"

        from unittest.mock import patch

        contaminated = (
            "4월 13일 (월) 리치 텍스트 메시지 자세한 내용을 보려면 Enter를 누르세요 "
            "갤럭시 S26 울트라는 6.9형 디스플레이와 200MP 카메라를 제공합니다."
        )

        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={
                    "history": [contaminated],
                    "count": 1,
                    "fallback_diff_used": False,
                },
            ),
            patch("app.dom_extractor.extract_bot_message_texts", return_value=[contaminated]),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=[contaminated]),
            patch("app.dom_extractor.extract_visible_chat_text", return_value=contaminated),
            patch("app.dom_extractor.extract_visible_text_blocks", return_value=[contaminated]),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext(), question="갤럭시 버즈3 프로 방수와 ANC 알려줘")

        assert payload["answer"] == ""
        assert payload["extraction_source"] == "unknown"
        assert payload["carryover_detected"] is True

    def test_truncated_candidate_is_not_accepted_as_success_answer(self):
        class DummyContext:
            baseline_bot_count = 1
            baseline_bot_messages = ["이전 답변"]
            baseline_message_nodes_snapshot = ["이전 답변"]
            baseline_visible_blocks = ["이전 답변"]
            baseline_last_answer = "이전 답변"
            baseline_topic_family = "unknown"

        from unittest.mock import patch

        truncated = "색상은 블루 기준으로"

        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={
                    "history": [truncated],
                    "count": 1,
                    "fallback_diff_used": False,
                },
            ),
            patch("app.dom_extractor.extract_bot_message_texts", return_value=[truncated]),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=[truncated]),
            patch("app.dom_extractor.extract_visible_chat_text", return_value=truncated),
            patch("app.dom_extractor.extract_visible_text_blocks", return_value=[truncated]),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext(), question="갤럭시 북5 프로 혜택 알려줘")

        assert payload["answer"] == ""
        assert payload["truncated_detected"] is True

    def test_payload_exposes_keyword_coverage_for_selected_candidate(self):
        class DummyContext:
            baseline_bot_count = 0
            baseline_bot_messages = []
            baseline_message_nodes_snapshot = []
            baseline_visible_blocks = []
            baseline_last_answer = ""
            baseline_topic_family = "unknown"

        from unittest.mock import patch

        answer = "갤럭시 버즈3 프로는 적응형 노이즈 캔슬링과 IP57 방수를 지원합니다."

        with (
            patch("app.dom_extractor.extract_structured_message_history", return_value={"history": [answer], "count": 1, "fallback_diff_used": False}),
            patch("app.dom_extractor.extract_bot_message_texts", return_value=[answer]),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=[answer]),
            patch("app.dom_extractor.extract_visible_chat_text", return_value=answer),
            patch("app.dom_extractor.extract_visible_text_blocks", return_value=[answer]),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext(), question="갤럭시 버즈3 프로 ANC와 방수 알려줘")

        assert payload["answer"] == answer
        assert payload["keyword_coverage_score"] >= 0.34

    def test_answer_ignores_feedback_timestamp_meta(self):
        class DummyContext:
            baseline_bot_count = 1
            baseline_bot_messages = ["구매 상담사와 채팅 하세요"]
            baseline_message_nodes_snapshot = ["구매 상담사와 채팅 하세요"]
            baseline_visible_blocks = ["구매 상담사와 채팅 하세요"]

        from unittest.mock import patch

        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={
                    "history": [
                        "구매 상담사와 채팅 하세요",
                        "좋아요 싫어함 오전 1:43",
                        "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.",
                    ],
                    "count": 3,
                    "fallback_diff_used": False,
                },
            ),
            patch(
                "app.dom_extractor.extract_bot_message_texts",
                return_value=[
                    "구매 상담사와 채팅 하세요",
                    "좋아요 싫어함 오전 1:43",
                    "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.",
                ],
            ),
            patch(
                "app.dom_extractor.diff_visible_text_against_baseline",
                return_value=["좋아요 싫어함 오전 1:43", "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."],
            ),
            patch(
                "app.dom_extractor.extract_visible_chat_text",
                return_value="구매 상담사와 채팅 하세요\n좋아요 싫어함 오전 1:43\n갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다.",
            ),
            patch(
                "app.dom_extractor.extract_visible_text_blocks",
                return_value=["좋아요 싫어함 오전 1:43", "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."],
            ),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext())

        assert payload["answer"] == "갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."
        assert payload["strict_candidates"] == ["갤럭시 S24 배터리 교체는 가까운 삼성 서비스센터에서 가능합니다."]

    def test_answer_uses_fallback_body_when_strict_has_only_followup_question(self):
        class DummyContext:
            baseline_bot_count = 1
            baseline_bot_messages = ["구매 상담사와 채팅 하세요"]
            baseline_message_nodes_snapshot = ["구매 상담사와 채팅 하세요"]
            baseline_visible_blocks = ["구매 상담사와 채팅 하세요"]

        from unittest.mock import patch

        answer_body = (
            "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요. "
            "가까운 센터에 방문 접수로 배터리 점검 후 교체가 가능합니다."
        )

        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={
                    "history": [
                        "구매 상담사와 채팅 하세요",
                        answer_body,
                        "가까운 서비스센터에서 바로 가능한가요?",
                    ],
                    "count": 3,
                    "fallback_diff_used": False,
                },
            ),
            patch(
                "app.dom_extractor.extract_bot_message_texts",
                return_value=[
                    "구매 상담사와 채팅 하세요",
                    "가까운 서비스센터에서 바로 가능한가요?",
                ],
            ),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=[]),
            patch(
                "app.dom_extractor.extract_visible_chat_text",
                return_value=f"구매 상담사와 채팅 하세요\n{answer_body}\n가까운 서비스센터에서 바로 가능한가요?",
            ),
            patch(
                "app.dom_extractor.extract_visible_text_blocks",
                return_value=[answer_body, "가까운 서비스센터에서 바로 가능한가요?"],
            ),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext())

        assert payload["strict_candidates"] == ["가까운 서비스센터에서 바로 가능한가요?"]
        assert payload["fallback_candidates"] == [answer_body, "가까운 서비스센터에서 바로 가능한가요?"]
        assert payload["all_candidates"] == ["가까운 서비스센터에서 바로 가능한가요?", answer_body]
        assert payload["answer"] == answer_body

    def test_post_baseline_candidates_flag_question_repetition_and_reject_echo(self):
        class DummyContext:
            baseline_bot_count = 0
            baseline_bot_messages = []
            baseline_message_nodes_snapshot = []
            baseline_visible_blocks = []

        from unittest.mock import patch

        question = "갤럭시 S26 울트라 사양 알려주세요"
        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={"history": [question], "count": 1, "fallback_diff_used": False},
            ),
            patch("app.dom_extractor.extract_bot_message_texts", return_value=[question]),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=[question]),
            patch("app.dom_extractor.extract_visible_chat_text", return_value=question),
            patch("app.dom_extractor.extract_visible_text_blocks", return_value=[question]),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext(), question=question)

        assert payload["question_repetition_detected"] is True
        assert payload["answer"] == ""
        assert payload["strict_candidates"] == []

    def test_post_baseline_candidates_use_selected_candidate_flags_not_any_candidate_flags(self):
        class DummyContext:
            baseline_bot_count = 0
            baseline_bot_messages = []
            baseline_message_nodes_snapshot = []
            baseline_visible_blocks = []
            baseline_last_answer = ""
            baseline_topic_family = "unknown"

        from unittest.mock import patch

        question = "갤럭시 버즈3 프로 방수와 ANC 알려줘"
        selected_answer = "갤럭시 버즈3 프로는 IP57 방수와 적응형 노이즈 캔슬링을 지원합니다."

        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={"history": [question, selected_answer], "count": 2, "fallback_diff_used": False},
            ),
            patch("app.dom_extractor.extract_bot_message_texts", return_value=[question, selected_answer]),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=[question, selected_answer]),
            patch("app.dom_extractor.extract_visible_chat_text", return_value=f"{question}\n{selected_answer}"),
            patch("app.dom_extractor.extract_visible_text_blocks", return_value=[question, selected_answer]),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext(), question=question)

        assert payload["answer"] == selected_answer
        assert payload["question_repetition_detected"] is False
        assert payload["carryover_detected"] is False

    def test_post_baseline_candidates_flag_truncated_cleaned_answer(self):
        class DummyContext:
            baseline_bot_count = 0
            baseline_bot_messages = []
            baseline_message_nodes_snapshot = []
            baseline_visible_blocks = []

        from unittest.mock import patch

        answer = "운동용으로도 매칭이 ."
        with (
            patch(
                "app.dom_extractor.extract_structured_message_history",
                return_value={"history": [answer], "count": 1, "fallback_diff_used": False},
            ),
            patch("app.dom_extractor.extract_bot_message_texts", return_value=[answer]),
            patch("app.dom_extractor.diff_visible_text_against_baseline", return_value=[answer]),
            patch("app.dom_extractor.extract_visible_chat_text", return_value=answer),
            patch("app.dom_extractor.extract_visible_text_blocks", return_value=[answer]),
        ):
            payload = build_post_baseline_answer_candidates(DummyContext(), question="갤럭시 버즈3 프로 방수 알려줘")

        assert payload["truncated_detected"] is True
        assert payload["cleaned_answer"] == ""
