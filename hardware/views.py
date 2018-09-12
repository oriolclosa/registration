from django.urls import reverse
from django.views.generic import TemplateView
from django_filters.views import FilterView
from django.template.loader import render_to_string
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django_tables2 import SingleTableMixin
from user.mixins import IsVolunteerMixin
from app import hackathon_variables
from app.mixins import TabsViewMixin
from user.models import User
from hardware.models import Item, ItemType, Lending, Request
from hardware.tables import LendingTable, LendingFilter, RequestTable, RequestFilter


def hardware_tabs(user):
    if user.is_volunteer:
        return [
            ('Hardware Admin', reverse('hw_admin'), False),
            ('Requests', reverse('hw_requests'), False),
            ('Lendings', reverse('hw_lendings'), False)
        ]
    else:
        return [
            ('Hardware List', reverse('hw_list'), False),
            ('Lendings', reverse('hw_lendings'), False)
        ]


class HardwareAdminRequestsView(TabsViewMixin, IsVolunteerMixin, 
    SingleTableMixin, FilterView):
    template_name = 'hardware_requests.html'
    table_class = RequestTable
    table_pagination = {'per_page':50}
    filterset_class = RequestFilter

    def get_current_tabs(self):
        return hardware_tabs(self.request.user)

    def get_queryset(self):
        return Request.objects.all()

class HardwareLendingsView(TabsViewMixin, SingleTableMixin, FilterView):
    template_name = 'hardware_lendings.html'
    table_class = LendingTable
    table_pagination = {'per_page':50}
    filterset_class = LendingFilter

    def get_current_tabs(self):
        return hardware_tabs(self.request.user)

    def get_queryset(self):
        if self.request.user.is_volunteer:
            return Lending.objects.all()
        else:
            return Lending.objects.get_queryset().filter(user=self.request.user)


class HardwareListView(LoginRequiredMixin, TabsViewMixin, TemplateView):
    template_name = 'hardware_list.html'

    def get_current_tabs(self):
        return hardware_tabs(self.request.user)

    def get_context_data(self, **kwargs):
        context = super(HardwareListView, self).get_context_data(**kwargs)
        context['hw_list'] = ItemType.objects.all()
        requests = Request.objects.get_active_by_user(self.request.user)
        context['requests'] = {
            x.item_type.id: x.get_remaining_time() for x in requests
        }
        return context

    def req_item(self, request):
        item = ItemType.objects.get(id=request.POST['item_id'])
        if item.get_available_count() > 0:
            item.make_request(request.user)
            return JsonResponse({
                'ok': True,
                'minutes': hackathon_variables.REQUEST_TIME
            })

        return JsonResponse({'msg': "ERROR: There are no items available"})

    def check_availability(self, request):
        item_ids = request.POST['item_ids[]']
        items = ItemType.objects.filter(id__in=item_ids)
        available_items = []
        for item in items:
            if item.get_available_count() > 0:
                available_items.append({
                    "id": item.id,
                    "name": item.name
                })

        return JsonResponse({
            'available_items': available_items
        })


    def post(self, request):
        if request.is_ajax:
            if 'req_item' in request.POST:
                return self.req_item(request)
            if 'check_availability' in request.POST:
                return self.check_availability(request)


class HardwareAdminView(IsVolunteerMixin, TabsViewMixin, TemplateView):
    template_name = 'hardware_admin.html'

    def init_and_toast(self, msg):
        """
        Finishes a process and goes back to the beginning while
        showing a toast
        """
        html = render_to_string("include/hardware_admin_init.html", {
            'hw_list': ItemType.objects.all(),
        })
        return JsonResponse({
            'content': html,
            'msg': msg
        })

    def get_lists(self, request):
        """
        When a user has a request or a lending we get the lists
        to proceed
        """
        target_user = User.objects.filter(email=request.POST['email'])
        if not target_user.exists():
            #In this case we don't want to return to the initial page
            return JsonResponse({
                'msg': "ERROR: The user doesn't exist"
            })

        requests = Request.objects.get_active_by_user(target_user.first())
        lendings = Lending.objects.get_active_by_user(target_user.first())
        html = render_to_string("include/hardware_admin_user.html", {
            'requests': requests,
            'lendings': lendings
        })
        return JsonResponse({
            'content': html
        })

    def select_request(self, request):
        """
        We selected a request to process a lending. Then we show a list
        with the available items of that type
        """
        request_obj = Request.objects.get(id=request.POST['request_id'])
        if not request_obj.is_active():
            return self.init_and_toast("ERROR: The request has expired")

        available_items = request_obj.item_type.get_lendable_items()
        html = render_to_string("include/hardware_admin_lending.html", {
            'items': available_items,
            'request_id': request.POST['request_id']
        })
        return JsonResponse({'content': html})

    def return_item(self, request):
        """
        We selected a lending to end it
        """
        lending = Lending.objects.get(id=request.POST['lending_id'])
        if not lending.is_active():
            return self.init_and_toast("ERROR: The item was not lent")

        lending.return_time = timezone.now()
        lending.save()
        return self.init_and_toast("The item has been returned succesfully")

    def make_lending(self, request):
        """
        Once we choose the item, we can now make the lending
        and finish the process
        """
        item = Item.objects.get(id=request.POST['item_id'])
        if not item.can_be_lent():
            return self.init_and_toast("ERROR: The item is not available")

        request_obj = Request.objects.get(id=request.POST['request_id'])
        lending = Lending(user=request_obj.user, item=item)
        lending.save()
        request_obj.lending = lending
        request_obj.save()
        return self.init_and_toast("The item has been lent succesfully")

    def select_type_noreq(self, request):
        """
        When a hacker doesn't have a request, we first select the hardware
        """
        item_type = ItemType.objects.get(id=request.POST['type_id'])
        if item_type.get_available_count() <= 0:
            return self.init_and_toast("ERROR: There are no items available")

        available_items = item_type.get_lendable_items()
        html = render_to_string("include/hardware_admin_lending.html", {
            'items': available_items,
        })
        return JsonResponse({'content': html})

    def select_item_noreq(self, request):
        """
        We selected an item without request. We still need a user
        """
        item = Item.objects.get(id=request.POST['item_id'])
        if not item.can_be_lent():
            return self.init_and_toast("ERROR: The item is not available")

        html = render_to_string("include/hardware_user_email.html", {
            'item_id': item.id
        })
        return JsonResponse({
            'content': html
        })

    def get_user_noreq(self, request):
        """
        We can make the lending without request now
        """
        item = Item.objects.get(id=request.POST['item_id'])
        target_user = User.objects.filter(email=request.POST['email'])
        if not target_user.exists():
            #In this case we don't want to return to the initial page
            return JsonResponse({
                'msg': "ERROR: The user doesn't exist"
            })
        if not item.can_be_lent():
            return self.init_and_toast("ERROR: The item is not available")

        lending = Lending(user=target_user.first(), item=item)
        lending.save()
        return self.init_and_toast("The item has been lent succesfully")

    def post(self, request):
        if request.is_ajax:
            if 'get_lists' in request.POST:
                return self.get_lists(request)
            if 'select_request' in request.POST:
                return self.select_request(request)
            if 'return_item' in request.POST:
                return self.return_item(request)
            if 'make_lending' in request.POST:
                return self.make_lending(request)
            if 'select_type_noreq' in request.POST:
                return self.select_type_noreq(request)
            if 'select_item_noreq' in request.POST:
                return self.select_item_noreq(request)
            if 'get_user_noreq' in request.POST:
                return self.get_user_noreq(request)
            if 'back' in request.POST:
                return self.init_and_toast("")

    def get_current_tabs(self):
        return hardware_tabs(self.request.user)

    def get_context_data(self, **kwargs):
        context = super(HardwareAdminView, self).get_context_data(**kwargs)
        context['hw_list'] = ItemType.objects.all()
        return context