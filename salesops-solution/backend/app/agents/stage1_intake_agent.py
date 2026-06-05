"""Stage 1 — Intake & Classification (v2 design, 7 sub-steps).

Per ADR-001 / 002 / 003 in SOLUTION.md:

  1.1  Receive inbound communication        — implicit (ctx.email already populated)
  1.2  Heuristic spam pre-screen            — regex on subject + sender; cheap gate
  1.3  Light attachment extraction          — azure_doc_intelligence with max_pages=3
  1.4  Detect language                      — heuristic + LLM, both run, agreement check
  1.5  Translate to English                 — LLM, KB-aware; skipped if EN
  1.6  LLM spam check                       — LLM on translated subject + body
  1.7  Classify intent                      — LLM, KB-driven, full reasoning surfaced
"""
from __future__ import annotations

import time
from pathlib import Path

from ..models import Pipeline
from .base import AgentContext, AgentResult, BaseAgent
from .tools.azure_doc_intelligence_tool import AzureDocIntelligenceTool
from .tools.classify_intent_tool import ClassifyIntentTool
from .tools.claude_vision_tool import ClaudeVisionTool
from .tools.detect_csr_override_tool import DetectCsrOverrideTool
from .tools.detect_language_tool import DetectLanguageTool
from .tools.detect_spam_tool import DetectSpamTool
from .tools.llm_spam_check_tool import LlmSpamCheckTool
from .tools.override_pass_tool import OverridePassTool
from .tools.read_tool import ReadTool
# === v1.1 TASK-9 START ===
from .tools.shadow_classifier_tool import ShadowClassifierTool
# === v1.1 TASK-9 END ===
from .tools.translate_tool import TranslateTool


_OCR_TYPES = {"pdf", "docx", "xlsx", "xls", "doc"}
_VISION_TYPES = {"image", "png", "jpg", "jpeg", "gif", "tif", "tiff", "bmp", "webp"}
_TEXT_TYPES = {"text", "txt", "csv", "json", "html", "htm"}


def _attachment_kind(att: dict) -> str:
    raw = (att.get("type") or "").lower()
    if raw:
        if raw in _OCR_TYPES:
            return "ocr"
        if raw in _VISION_TYPES:
            return "vision"
        if raw in _TEXT_TYPES:
            return "text"
    name = att.get("name") or att.get("path") or ""
    ext = Path(name).suffix.lower().lstrip(".")
    if ext in _OCR_TYPES:
        return "ocr"
    if ext in _VISION_TYPES:
        return "vision"
    if ext in _TEXT_TYPES:
        return "text"
    return "unknown"


class Stage1IntakeAgent(BaseAgent):
    """Receive → heuristic-spam → light-extract → language(heuristic+LLM) → translate → llm-spam → classify."""

    stage_key = "intake"
    stage_label = "Intake & Classification"
    tools = [
        ReadTool(),
        AzureDocIntelligenceTool(),
        ClaudeVisionTool(),
        DetectSpamTool(),
        DetectLanguageTool(),
        TranslateTool(),
        LlmSpamCheckTool(),
        ClassifyIntentTool(),
        OverridePassTool(),
        DetectCsrOverrideTool(),
        # === v1.1 TASK-9 ===
        ShadowClassifierTool(),
    ]

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.perf_counter()
        tool_results = []
        guardrails: list[str] = []
        try:
            email = ctx.email or {}
            subject = email.get("subject") or ""
            body = email.get("body") or ""
            attachments = email.get("attachments") or []

            # ---- 1.2 Heuristic spam pre-screen --------------------------------
            heur_spam_res = self.invoke_tool(ctx, "detect_spam", email=email)
            tool_results.append(heur_spam_res)
            heuristic_is_spam = bool(heur_spam_res.data.get("is_spam")) if heur_spam_res.ok else False
            ctx.intake["heuristic_spam"] = heur_spam_res.data if heur_spam_res.ok else None

            # ---- 1.3 Light attachment extraction (Stage 1 cap: 3 pages) -------
            attachment_text_parts: list[str] = []
            for att in attachments:
                kind = _attachment_kind(att)
                name = att.get("name") or att.get("path") or "<unnamed>"
                if kind == "ocr":
                    res = self.invoke_tool(
                        ctx, "azure_doc_intelligence",
                        name=att.get("path") or name,
                        url=att.get("url"),
                        max_pages=3,
                    )
                    tool_results.append(res)
                    if res.ok:
                        text = (res.data.get("text") or "")
                        if text:
                            attachment_text_parts.append(f"--- {name} (light extract) ---\n{text}")
                elif kind == "vision":
                    res = self.invoke_tool(ctx, "vision_ocr", image_paths=[att.get("path") or name])
                    tool_results.append(res)
                    if res.ok:
                        text = (res.data.get("text") or "")
                        if text:
                            attachment_text_parts.append(f"--- {name} (image) ---\n{text}")
                elif kind == "text":
                    res = self.invoke_tool(ctx, "read_attachment", name=att.get("path") or name)
                    tool_results.append(res)
                    if res.ok:
                        text = (res.data.get("content") or "")
                        if text:
                            attachment_text_parts.append(f"--- {name} (text) ---\n{text}")
                else:
                    guardrails.append(f"unknown_attachment_type: {name}")

            attachment_text = "\n\n".join(attachment_text_parts)
            ctx.intake["attachment_text"] = attachment_text
            ctx.intake["attachment_text_chars"] = len(attachment_text)

            # ---- 1.4 Detect language (heuristic + LLM, on body + attachment) --
            lang_input = f"{subject}\n{body}\n{attachment_text[:1500]}".strip()
            lang_res = self.invoke_tool(ctx, "detect_language", text=lang_input)
            tool_results.append(lang_res)
            language = (lang_res.data.get("language") if lang_res.ok else None) or email.get("language_hint") or "en"
            ctx.intake["language"] = language
            ctx.intake["language_confidence"] = lang_res.data.get("confidence") if lang_res.ok else None
            ctx.intake["language_method"] = lang_res.data.get("method") if lang_res.ok else None
            ctx.intake["language_agreement"] = lang_res.data.get("agreement") if lang_res.ok else None

            # ---- 1.5 Translate to English (skipped if EN) --------------------
            # We translate the email body and EACH attachment separately so the
            # trace UI can show a per-source breakdown (subject+body translation
            # plus a clickable chip per attachment with its own translation).
            classify_body = body
            translated_text: str | None = None
            per_source_translations: list[dict] = []
            if language and language != "en":
                # 1.5a — translate subject + body
                body_input = f"Subject: {subject}\n\n{body}".strip()
                if body_input:
                    body_res = self.invoke_tool(
                        ctx, "translate_to_english",
                        text=body_input,
                        source_language=language,
                    )
                    tool_results.append(body_res)
                    if body_res.ok and body_res.data.get("translated_text"):
                        translated_text = body_res.data["translated_text"]
                        ctx.intake["translated_body"] = translated_text
                        classify_body = translated_text
                        per_source_translations.append({
                            "source": "email_body",
                            "label": "Email subject + body",
                            "filename": None,
                            "input_chars": body_res.data.get("input_chars"),
                            "output_chars": body_res.data.get("output_chars"),
                            "translated_text": translated_text,
                            "input_text": body_input,
                            "provider": body_res.data.get("provider_label"),
                            "source_language": body_res.data.get("source_language"),
                        })
                    else:
                        guardrails.append("translate_failed_using_original_body")

                # 1.5b — translate each attachment that has extracted text
                for attachment_block in attachment_text_parts:
                    # Each entry from 1.3 is "--- {name} (kind) ---\n{text}"
                    lines = attachment_block.split("\n", 1)
                    header = lines[0] if lines else ""
                    text = lines[1] if len(lines) > 1 else ""
                    if not text.strip():
                        continue
                    name = header.replace("---", "").strip()
                    if " (" in name:
                        name = name.split(" (", 1)[0]
                    att_res = self.invoke_tool(
                        ctx, "translate_to_english",
                        text=text[:6000],
                        source_language=language,
                    )
                    tool_results.append(att_res)
                    if att_res.ok and att_res.data.get("translated_text"):
                        per_source_translations.append({
                            "source": "attachment",
                            "label": f"Attachment: {name}",
                            "filename": name,
                            "input_chars": att_res.data.get("input_chars"),
                            "output_chars": att_res.data.get("output_chars"),
                            "translated_text": att_res.data.get("translated_text"),
                            "input_text": text,
                            "provider": att_res.data.get("provider_label"),
                            "source_language": att_res.data.get("source_language"),
                        })
                    else:
                        guardrails.append(f"translate_attachment_failed: {name}")
            ctx.intake["per_source_translations"] = per_source_translations

            # ---- 1.6 LLM spam check (on translated text) ---------------------
            llm_spam_res = self.invoke_tool(
                ctx,
                "llm_spam_check",
                email={"from": email.get("from"), "subject": subject},
                body_english=classify_body,
            )
            tool_results.append(llm_spam_res)
            llm_is_spam = bool(llm_spam_res.data.get("is_spam")) if llm_spam_res.ok else False
            ctx.intake["llm_spam"] = llm_spam_res.data if llm_spam_res.ok else None

            # ---- 1.7 Classify intent (skipped if both spam signals concur) ---
            classify_email = dict(email)
            classify_email["body"] = classify_body
            intent_res = self.invoke_tool(ctx, "classify_intent", email=classify_email)
            tool_results.append(intent_res)
            if intent_res.ok:
                for k, v in intent_res.data.items():
                    if k == "language":
                        continue
                    ctx.intake[k] = v
            else:
                ctx.intake.setdefault("intent", "general_inquiry")
                ctx.intake.setdefault("intent_confidence", 0.0)
                ctx.intake.setdefault("spam", False)
                guardrails.append(f"classify_intent_failed: {intent_res.error}")

            # ---- 1.7a Override-pass — global override book (two-stage classifier) ----
            # Mirrors prior Keysight POC step 39: Context-pass picks the surface
            # intent (above), Override-pass applies the global override book
            # verbatim and may revise the intent if a rule fires (e.g., Rule 25
            # "PO# only inside SOA attachment is not a real PO").
            override_pass_res = self.invoke_tool(
                ctx, "override_pass",
                email={"from": email.get("from"), "subject": subject},
                body_english=classify_body,
                context_pass_intent=ctx.intake.get("intent") or "",
            )
            tool_results.append(override_pass_res)
            override_pass_data = override_pass_res.data if override_pass_res.ok else {}
            ctx.intake["override_pass"] = override_pass_data
            if override_pass_data.get("should_override") and override_pass_data.get("revised_intent"):
                pre_intent = ctx.intake.get("intent")
                new_intent = override_pass_data["revised_intent"]
                if new_intent != pre_intent:
                    ctx.intake["intent_pre_override_pass"] = pre_intent
                    ctx.intake["intent"] = new_intent
                    fired_count = len(override_pass_data.get("rules_fired") or [])
                    guardrails.append(
                        f"override_pass_revised_intent: {pre_intent} -> {new_intent} "
                        f"({fired_count} rules fired @ {override_pass_data.get('override_confidence', 0):.2f})"
                    )

            # ---- 1.7b CSR-instruction override detection ---------------------
            # If a CSR forwarded the email with explicit override instructions
            # ("process as hold release", "do not auto-respond", "escalate to
            # legal"), they should win over the auto-classifier. This is a
            # SEPARATE LLM micro-step so the classifier stays focused on the
            # email's surface intent and the override pass focuses only on
            # internal-staff directives.
            override_res = self.invoke_tool(
                ctx, "detect_csr_override",
                email={"from": email.get("from"), "subject": subject},
                body_english=classify_body,
                classifier_intent=ctx.intake.get("intent") or "",
            )
            tool_results.append(override_res)
            override_data = override_res.data if override_res.ok else {}
            ctx.intake["csr_override"] = override_data
            if override_data.get("has_override"):
                kind = override_data.get("override_kind") or "none"
                inst = override_data.get("override_instruction") or ""
                guardrails.append(
                    f"csr_override_detected[{kind}]: {inst[:200]}"
                )
                # Apply intent_override directly. Other override kinds are
                # advisory metadata for the orchestrator/HITL UI to consume.
                if kind == "intent_override" and override_data.get("override_intent"):
                    pre = ctx.intake.get("intent")
                    new_intent = override_data["override_intent"]
                    if new_intent != pre:
                        ctx.intake["intent_pre_override"] = pre
                        ctx.intake["intent"] = new_intent
                        guardrails.append(
                            f"intent_overridden_by_csr: {pre} -> {new_intent}"
                        )
                if kind == "force_track" and override_data.get("override_track"):
                    ctx.intake["track_hint_pre_override"] = ctx.intake.get("track_hint")
                    ctx.intake["track_hint"] = override_data["override_track"]

            # === v1.1 TASK-9 START === Shadow classifier (logged-only third pass).
            # Toggled via KB rule shadow_classifier.config.body.enabled — when off
            # the tool returns {skipped: True} immediately. When on, runs alongside
            # the primary classifier and records agreement.
            shadow_res = self.invoke_tool(
                ctx, "shadow_classifier",
                email={"from": email.get("from"), "subject": subject},
                body_english=classify_body,
                primary_intent=ctx.intake.get("intent") or "",
            )
            tool_results.append(shadow_res)
            shadow_data = shadow_res.data if shadow_res.ok else {}
            ctx.intake["shadow_classification"] = shadow_data
            if shadow_data and not shadow_data.get("skipped"):
                guardrails.append(
                    f"shadow_classifier_ran: agreement={shadow_data.get('agreement_with_primary')}"
                )
                # Persist on Pipeline for the Ops dashboard agreement-rate column.
                from ..models import Pipeline as _Pipe
                pipe_row = ctx.db.get(_Pipe, ctx.pipeline_id)
                if pipe_row:
                    pipe_row.shadow_classification = shadow_data
                    ctx.db.commit()
            # === v1.1 TASK-9 END ===

            # ---- Spam reconciliation (heuristic + LLM + classifier all considered) -----
            # The classifier (classify_intent) is canonical because it picks between
            # `spam` (malicious) and `out_of_scope` (legitimate non-customer). The
            # heuristic + llm_spam_check are CORROBORATION — they only force
            # intent=spam if the classifier agrees OR returns a customer-business
            # intent (where flagging spam is a real correction). They do NOT
            # override the classifier when it returns out_of_scope (legitimate
            # promotional / transactional from a known sender).
            classifier_intent = ctx.intake.get("intent")
            classifier_says_spam = bool(ctx.intake.get("spam")) or classifier_intent == "spam"
            classifier_says_terminal = classifier_intent in {"spam", "out_of_scope"}
            ctx.intake["spam_signals"] = {
                "heuristic": heuristic_is_spam,
                "llm": llm_is_spam,
                "classifier": classifier_says_spam,
                "classifier_intent": classifier_intent,
                "heuristic_reasons": heur_spam_res.data.get("reasons") if heur_spam_res.ok else [],
                "llm_reasoning": (llm_spam_res.data.get("reasoning") if llm_spam_res.ok else None),
                "llm_category": (llm_spam_res.data.get("category") if llm_spam_res.ok else None),
            }

            # Force spam ONLY when (a) the classifier already says spam, OR (b) the
            # classifier returned a customer-business intent (po_intake, etc.) but
            # the heuristic/LLM caught real malicious content that the classifier
            # missed. We DO NOT override out_of_scope, because the classifier's
            # out_of_scope decision means "legitimate non-customer" — heuristic/LLM
            # noise on promotional content is expected and doesn't change the truth.
            if classifier_says_spam:
                ctx.intake["spam"] = True
                ctx.intake["intent"] = "spam"
                guardrails.append("spam_confirmed_by_classifier")
                if heuristic_is_spam:
                    guardrails.append("spam_corroborated_by_heuristic")
                if llm_is_spam:
                    guardrails.append("spam_corroborated_by_llm")
            elif classifier_intent == "out_of_scope":
                # Respect the classifier — don't force spam even if llm_spam_check
                # flagged the email as promotional. Note both signals for the audit
                # trail so a CSR can see they fired.
                if heuristic_is_spam or llm_is_spam:
                    guardrails.append(
                        "spam_signals_overridden_by_classifier: classifier returned "
                        "out_of_scope (legitimate non-customer); heuristic/LLM-spam "
                        "noise on promotional content does not change that"
                    )
            elif heuristic_is_spam or llm_is_spam:
                # Classifier returned a customer-business intent BUT a spam signal
                # fired. We need BOTH heuristic AND LLM agreeing OR a low-confidence
                # classifier to override — a single weak spam signal isn't enough to
                # trump a high-confidence classifier. Otherwise we'd false-positive
                # legitimate enterprise customer mail (raytheon-elseg.com, etc.)
                # whenever the LLM saw an unfamiliar sender domain.
                classifier_conf = float(ctx.intake.get("intent_confidence") or 0.0)
                both_signals_agree = heuristic_is_spam and llm_is_spam
                classifier_low_conf = classifier_conf < 0.85
                if both_signals_agree or classifier_low_conf:
                    ctx.intake["spam"] = True
                    ctx.intake["intent"] = "spam"
                    if both_signals_agree:
                        guardrails.append(
                            f"spam_caught_by_both_heuristic_and_llm "
                            f"(classifier_intent={classifier_intent} @ {classifier_conf:.2f} overridden)"
                        )
                    else:
                        which = "heuristic+llm" if (heuristic_is_spam and llm_is_spam) else ("llm" if llm_is_spam else "heuristic")
                        guardrails.append(
                            f"spam_signal[{which}]_overrode_low_confidence_classifier "
                            f"(was {classifier_intent} @ {classifier_conf:.2f})"
                        )
                else:
                    # Single weak spam signal vs high-confidence classifier on a
                    # business intent — respect the classifier. Just log the signal
                    # for the audit trail.
                    fired = "heuristic+llm" if (heuristic_is_spam and llm_is_spam) else ("llm" if llm_is_spam else "heuristic")
                    llm_reason = (llm_spam_res.data.get("reasoning") if llm_spam_res.ok else "") or ""
                    guardrails.append(
                        f"spam_signal[{fired}]_overridden_by_high_conf_classifier "
                        f"(classifier={classifier_intent} @ {classifier_conf:.2f}; "
                        f"weak_spam_reason={llm_reason[:140]})"
                    )

            self._persist(ctx)
            return AgentResult(
                stage=self.stage_key,
                output=ctx.intake,
                tool_results=tool_results,
                guardrails_fired=guardrails,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:
            return AgentResult(
                stage=self.stage_key,
                output={},
                tool_results=tool_results,
                guardrails_fired=[*guardrails, f"stage_error: {type(e).__name__}: {str(e)[:300]}"],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def _persist(self, ctx: AgentContext) -> None:
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return
        pipe.intent = ctx.intake.get("intent")
        pipe.language = ctx.intake.get("language")
        ctx.db.commit()
