import logging
import socket
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)


def offers_page_fallback(retry_state):
    logger.warning(
        f"Database unavailable after retries. Activating Fallback. "
        f"Exception: {retry_state.outcome.exception()}"
    )
    return {"farms": [], "specializations": [], "current_farm": None, "items": [], "is_fallback": True}


class OffersService:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(0.3),
        retry=retry_if_exception_type((OperationalError, socket.timeout, OSError)),        retry_error_callback=offers_page_fallback,



    )
    def get_offers_page_data(self, farms_query, specializations_query, current_farm_query, items_query):
        """
        Виконує ВСІ запити до БД, потрібні для сторінки /offers,
        єдиним блоком з Retry (3 спроби) і Fallback при недоступності PostgreSQL.
        """
        farms = farms_query.all()
        specializations = specializations_query.all()
        current_farm = current_farm_query.first() if current_farm_query is not None else None
        items = items_query.all()
        return {
            "farms": farms,
            "specializations": specializations,
            "current_farm": current_farm,
            "items": items,
            "is_fallback": False,
        }