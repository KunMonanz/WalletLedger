from rest_framework.pagination import CursorPagination


class LedgerPagination(CursorPagination):
    page_size = 20
    max_page_size = 100
    ordering = "-created_at"
    cursor_query_param = "cursor"
