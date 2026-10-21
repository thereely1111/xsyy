from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Problem
from app.services.ai_service import ai_service
import logging

logger = logging.getLogger(__name__)

MATH_CONFIDENCE_THRESHOLD = 0.7


class ProblemValidationError(Exception):
    def __init__(self, message: str, code: str = "VALIDATION_FAILED"):
        self.message = message
        self.code = code
        super().__init__(self.message)


async def validate_problem_content(
    content: str,
    image_base64: str = None,
    db: AsyncSession = None,
    author_id: int = None
) -> dict:
    logger.info(f"Starting problem validation | author_id={author_id}")

    if image_base64:
        validation_result = await ai_service.check_if_math_from_image(image_base64)
        logger.info(f"Image validation result: {validation_result}")
    else:
        validation_result = await ai_service.check_if_math(content)
        logger.info(f"Text validation result: {validation_result}")

    if not validation_result.get("is_math", False):
        logger.warning(f"Content is not a math problem | confidence={validation_result.get('confidence', 0)}")
        raise ProblemValidationError(
            message="提交的内容不是有效的数学题目，请输入数学相关问题",
            code="NOT_MATH_PROBLEM"
        )

    if validation_result.get("confidence", 0) < MATH_CONFIDENCE_THRESHOLD:
        logger.warning(f"Math problem confidence too low: {validation_result.get('confidence')}")
        raise ProblemValidationError(
            message=f"数学题目置信度不足（{validation_result.get('confidence', 0):.2f}），请确保输入的是清晰的数学问题",
            code="LOW_CONFIDENCE"
        )

    return {
        "is_math": True,
        "confidence": validation_result.get("confidence", 1.0),
        "has_graph": validation_result.get("has_graph", False),
        "reason": validation_result.get("reason", "")
    }


async def extract_core_content(content: str) -> str:
    logger.info("Starting core content extraction")
    cleaned = await ai_service.extract_core_question(content)

    if len(cleaned) < 5:
        logger.warning(f"Extracted content too short ({len(cleaned)} chars), using raw content")
        return content

    logger.info(f"Core content extracted successfully | original_len={len(content)} cleaned_len={len(cleaned)}")
    return cleaned


async def create_problem_with_validation(
    content: str,
    title: str,
    description: str = None,
    image_url: str = None,
    image_base64: str = None,
    db: AsyncSession = None,
    author_id: int = None
) -> Problem:
    validation = await validate_problem_content(
        content=content,
        image_base64=image_base64,
        db=db,
        author_id=author_id
    )

    cleaned_content = await extract_core_content(content)

    problem = Problem(
        author_id=author_id,
        title=title,
        description=description,
        content=content,
        cleaned_content=cleaned_content,
        image_url=image_url,
        primary_tag="数学",
        secondary_tags=[],
        difficulty="medium",
        knowledge_points=[],
        view_count=0,
        like_count=0,
        favorite_count=0,
        is_audited=0
    )

    if db:
        db.add(problem)
        await db.commit()
        await db.refresh(problem)

    logger.info(f"Problem created successfully | id={problem.id if db else 'pending'}")
    return problem


problem_service = {
    "validate": validate_problem_content,
    "create": create_problem_with_validation
}
