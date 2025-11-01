from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from .models import Trip
from .serializers import TripSerializer
from .services import get_route
import os


class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all().order_by('-created_at')
    serializer_class = TripSerializer

    @action(detail=False, methods=['post'])
    def plan_route(self, request):
        try:
            current_location = request.data.get("current_location")
            pickup_location = request.data.get("pickup_location")
            dropoff_location = request.data.get("dropoff_location")
            current_cycle_used = float(request.data.get("current_cycle_used", 0) or 0)
            hours_already_used = float(request.data.get("hours_already_used", 0) or 0)
            api_key = os.getenv("ORS_API_KEY")

            if not all([current_location, pickup_location, dropoff_location]):
                return Response(
                    {"error": "All locations (current, pickup, and dropoff) are required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # --- Helper: safely parse coordinates ---
            def to_coords(loc):
                parts = [float(x.strip()) for x in loc.split(",")]
                if len(parts) != 2:
                    raise ValueError(f"Invalid coordinate format for '{loc}'. Expected 'lat,lon' or 'lon,lat'.")

                # Smart detection: identify which value is latitude/longitude
                if abs(parts[0]) > 30 and abs(parts[1]) <= 30:
                    # lon, lat
                    lon, lat = parts
                else:
                    # lat, lon
                    lat, lon = parts
                return [lon, lat]

            current_coords = to_coords(current_location)
            pickup_coords = to_coords(pickup_location)
            dropoff_coords = to_coords(dropoff_location)

            # --- Get route from ORS ---
            route_data = get_route(current_coords, pickup_coords, dropoff_coords, api_key)

            # --- Handle both success and failure structures from ORS ---
            if not route_data:
                return Response(
                    {"error": "No response from the routing API."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Case 1: ORS GeoJSON-style result
            if "features" in route_data and route_data["features"]:
                route_summary = route_data["features"][0]["properties"]["summary"]
                distance_m = route_summary.get("distance", 0)
                duration_s = route_summary.get("duration", 0)

            # Case 2: ORS JSON route-style result
            elif "routes" in route_data and route_data["routes"]:
                route_summary = route_data["routes"][0]["summary"]
                distance_m = route_summary.get("distance", 0)
                duration_s = route_summary.get("duration", 0)
            else:
                return Response(
                    {"error": "No valid route found from the routing API.", "details": route_data},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # --- Compute metrics ---
            distance_km = round(distance_m / 1000, 2)
            duration_hours = round(duration_s / 3600, 2)
            total_hours = hours_already_used + duration_hours

            # --- Save the Trip ---
            trip = Trip.objects.create(
                current_location=current_location,
                pickup_location=pickup_location,
                dropoff_location=dropoff_location,
                current_cycle_used=current_cycle_used,
                hours_already_used=hours_already_used,
                distance_km=distance_km,
                duration_hours=duration_hours
            )

            # --- Evaluate cycle usage ---
            if total_hours >= current_cycle_used:
                cycle_status = "EXCEEDED"
            elif total_hours >= 0.9 * current_cycle_used:
                cycle_status = "NEAR_LIMIT"
            else:
                cycle_status = "OK"

            # --- Return success response ---
            return Response({
                "trip": TripSerializer(trip).data,
                "route_summary": {
                    "distance_km": distance_km,
                    "duration_hours": duration_hours,
                    "cycle_status": cycle_status,
                    "hours_after_trip": total_hours
                },
                "route": route_data
            }, status=status.HTTP_200_OK)

        except ValueError as ve:
            return Response({"error": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # -----------------------------
    # 🚀 NEW IMPROVEMENTS BELOW
    # -----------------------------

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        trip = self.get_object()
        trip.status = 'IN_PROGRESS'
        trip.save()
        return Response({"message": "Trip started", "trip": TripSerializer(trip).data})

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        trip = self.get_object()
        trip.status = 'COMPLETED'
        trip.save()
        return Response({"message": "Trip completed", "trip": TripSerializer(trip).data})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        trip = self.get_object()
        trip.status = 'CANCELLED'
        trip.save()
        return Response({"message": "Trip cancelled", "trip": TripSerializer(trip).data})

    @action(detail=False, methods=['get'])
    def summary(self, request):
        stats = Trip.objects.aggregate(
            total_trips=Count('id'),
            total_distance=Sum('distance_km'),
            total_duration=Sum('duration_hours'),
            completed_trips=Count('id', filter=Q(status='COMPLETED')),
        )
        return Response(stats)

    @action(detail=True, methods=['get'])
    def eld_status(self, request, pk=None):
        trip = self.get_object()
        remaining_hours = trip.current_cycle_used - (trip.hours_already_used + trip.duration_hours)
        cycle_status = "EXCEEDED" if remaining_hours < 0 else "OK"
        return Response({
            "trip_id": trip.id,
            "cycle_status": cycle_status,
            "remaining_hours": max(0, remaining_hours)
        })
