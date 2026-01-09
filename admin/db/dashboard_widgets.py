from fastadmin import (
    DashboardWidgetAdmin,
    DashboardWidgetType,
    WidgetType,
    register_widget,
)
from django.db import connection
import datetime


@register_widget
class PostWidgetDashboard(DashboardWidgetAdmin):
    title = "Posts"
    x_field = "date"
    y_field = "count"
    dashboard_widget_type = DashboardWidgetType.ChartBar

    def get_data(self, min_x_field, max_x_field, period_x_field):

        def dictfetchall(cursor):
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        if not min_x_field:
            min_date = datetime.datetime.now(
                datetime.UTC
            ) - datetime.timedelta(days=360)
        else:
            min_date = datetime.datetime.fromisoformat(min_x_field)

        if not max_x_field:
            max_date = datetime.datetime.now(datetime.UTC)
        else:
            max_date = datetime.datetime.fromisoformat(max_x_field)

        if period_x_field not in {"day", "week", "month", "year"}:
            period_x_field = "month"

        with connection.cursor() as c:
            c.execute(
                """
                SELECT
                    date_trunc(%s, posts.created_at) AS date,
                    count(posts.id) AS count
                FROM posts
                WHERE posts.created_at BETWEEN %s AND %s
                GROUP BY date
                ORDER BY date
                """,
                [period_x_field, min_date, max_date],
            )

            results = dictfetchall(c)

        return {
            "results": results,
            "min_x_field": min_date.isoformat(),
            "max_x_field": max_date.isoformat(),
            "period_x_field": period_x_field,
        }
