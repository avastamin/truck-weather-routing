from datetime import datetime

from rest_framework import serializers

from api.domain.sampling import ALLOWED_INTERVALS_MILES, DEFAULT_INTERVAL_MILES

MAX_LOAD_LB = 200_000  # well above the 80,000 lb federal limit, to allow permitted loads


class PlanInputSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=200)
    destination = serializers.CharField(max_length=200)
    departure = serializers.DateTimeField()
    load_lb = serializers.FloatField(min_value=1, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(
        choices=ALLOWED_INTERVALS_MILES, default=DEFAULT_INTERVAL_MILES
    )

    def validate_departure(self, value):
        # DRF quietly assumes the server timezone for times without an offset. A truck's ETAs
        # depend on the real departure time, so require the offset explicitly.
        raw = self.initial_data.get("departure", "")
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is None:
            raise serializers.ValidationError(
                "Include a timezone offset, e.g. 2026-11-22T08:00:00-06:00."
            )
        return value
