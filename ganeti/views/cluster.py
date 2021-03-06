# Copyright (C) 2010 Oregon State University et al.
# Copyright (C) 2010 Greek Research and Technology Network
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.


import json
import os
import socket
import urllib2

from django import forms
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext
from django.template.defaultfilters import slugify

from object_permissions import get_model_perms, get_user_perms, grant, revoke, \
    get_users, get_groups, get_group_perms
from object_permissions.views.permissions import view_users, view_permissions

from logs.models import LogItem
log_action = LogItem.objects.log_action

from ganeti.models import *
from ganeti.views import render_403, render_404
from util.portforwarder import forward_port

# Regex for a resolvable hostname
FQDN_RE = r'^[\w]+(\.[\w]+)*$'


@login_required
def detail(request, cluster_slug):
    """
    Display details of a cluster
    """
    cluster = get_object_or_404(Cluster, slug=cluster_slug)
    user = request.user
    admin = True if user.is_superuser else user.has_perm('admin', cluster)
    if not admin:
        return render_403(request, "You do not have sufficient privileges")
    
    return render_to_response("cluster/detail.html", {
        'cluster': cluster,
        'user': request.user,
        'admin' : admin
        },
        context_instance=RequestContext(request),
    )


@login_required
def nodes(request, cluster_slug):
    """
    Display all nodes in a cluster
    """
    cluster = get_object_or_404(Cluster, slug=cluster_slug)
    user = request.user
    if not (user.is_superuser or user.has_perm('admin', cluster)):
        return render_403(request, "You do not have sufficient privileges")
    
    return render_to_response("node/table.html", \
                        {'cluster': cluster, 'nodes':cluster.nodes(True)}, \
        context_instance=RequestContext(request),
    )


@login_required
def virtual_machines(request, cluster_slug):
    """
    Display all virtual machines in a cluster.  Filtered by access the user
    has permissions for
    """
    cluster = get_object_or_404(Cluster, slug=cluster_slug)
    user = request.user
    admin = True if user.is_superuser else user.has_perm('admin', cluster)
    if not admin:
        return render_403(request, "You do not have sufficient privileges")
    
    if admin:
        vms = cluster.virtual_machines.all()
    else:
        vms = user.filter_on_perms(['admin'], VirtualMachine, cluster=cluster)
    
    return render_to_response("virtual_machine/table.html", \
                {'cluster': cluster, 'vms':vms}, \
                context_instance=RequestContext(request))


@login_required
def edit(request, cluster_slug=None):
    """
    Edit a cluster
    """
    if cluster_slug:
        cluster = get_object_or_404(Cluster, slug=cluster_slug)
    else:
        cluster = None
    
    user = request.user
    if not (user.is_superuser or (cluster and user.has_perm('admin', cluster))):
        return render_403(request, "You do not have sufficient privileges")
    
    if request.method == 'POST':
        form = EditClusterForm(request.POST, instance=cluster)
        if form.is_valid():
            cluster = form.save()
            # TODO Create post signal to import
            #   virtual machines on edit of cluster
            cluster.sync_virtual_machines()
            return HttpResponseRedirect(reverse('cluster-detail', \
                                                args=[cluster.slug]))
    
    elif request.method == 'DELETE':
        cluster.delete()
        return HttpResponse('1', mimetype='application/json')
    
    else:
        form = EditClusterForm(instance=cluster)
    
    return render_to_response("cluster/edit.html", {
        'form' : form,
        'cluster': cluster,
        },
        context_instance=RequestContext(request),
    )


@login_required
def list_(request):
    """
    List all clusters
    """
    user = request.user
    if user.is_superuser:
        cluster_list = Cluster.objects.all()
    else:
        cluster_list = user.get_objects_any_perms(Cluster, ['admin', 'create_vm'])
    return render_to_response("cluster/list.html", {
        'cluster_list': cluster_list,
        'user': request.user,
        },
        context_instance=RequestContext(request),
    )


@login_required
def users(request, cluster_slug):
    """
    Display all of the Users of a Cluster
    """
    cluster = get_object_or_404(Cluster, slug=cluster_slug)
    
    user = request.user
    if not (user.is_superuser or user.has_perm('admin', cluster)):
        return render_403(request, "You do not have sufficient privileges")
    
    url = reverse('cluster-permissions', args=[cluster.slug])
    return view_users(request, cluster, url, template='cluster/users.html')


@login_required
def permissions(request, cluster_slug, user_id=None, group_id=None):
    """
    Update a users permissions.
    """
    cluster = get_object_or_404(Cluster, slug=cluster_slug)
    user = request.user
    if not (user.is_superuser or user.has_perm('admin', cluster)):
        return render_403(request, "You do not have sufficient privileges")

    url = reverse('cluster-permissions', args=[cluster.slug])
    response, modified = view_permissions(request, cluster, url, user_id, group_id,
                            user_template='cluster/user_row.html',
                            group_template='cluster/group_row.html')
    
    # log changes if any.
    if modified:
        # log information about creating the machine
        log_action(user, cluster, "modified permissions")
    
    return response


class QuotaForm(forms.Form):
    """
    Form for editing user quota on a cluster
    """
    input = forms.TextInput(attrs={'size':5})
    
    user = forms.ModelChoiceField(queryset=ClusterUser.objects.all(), \
                                  widget=forms.HiddenInput)
    ram = forms.IntegerField(label='Memory (MB)', required=False, min_value=0, \
                             widget=input)
    virtual_cpus = forms.IntegerField(label='Virtual CPUs', required=False, \
                                    min_value=0, widget=input)
    disk = forms.IntegerField(label='Disk Space (MB)', required=False, \
                              min_value=0, widget=input)
    delete = forms.BooleanField(required=False, widget=forms.HiddenInput)


@login_required
def quota(request, cluster_slug, user_id):
    """
    Updates quota for a user
    """
    cluster = get_object_or_404(Cluster, slug=cluster_slug)
    user = request.user
    if not (user.is_superuser or user.has_perm('admin', cluster)):
        return render_403(request, "You do not have sufficient privileges")
    
    if request.method == 'POST':
        form = QuotaForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            cluster_user = data['user']
            if data['delete']:
                cluster.set_quota(cluster_user)
            else:
                quota = cluster.get_quota()
                same = data['virtual_cpus'] == quota['virtual_cpus'] \
                    and data['disk']==quota['disk'] \
                    and data['ram']==quota['ram']
                if same:
                    # same as default, set quota to default.
                    cluster.set_quota(cluster_user)
                else:
                    cluster.set_quota(cluster_user, data)
            
            # return updated html
            cluster_user = cluster_user.cast()
            url = reverse('cluster-permissions', args=[cluster.slug])
            if isinstance(cluster_user, (Profile,)):
                return render_to_response("cluster/user_row.html",
                    {'object':cluster, 'user':cluster_user.user, 'url':url})
            else:
                return render_to_response("cluster/group_row.html",
                    {'object':cluster, 'group':cluster_user.group, \
                     'url':url})
        
        # error in form return ajax response
        content = json.dumps(form.errors)
        return HttpResponse(content, mimetype='application/json')
    
    if user_id:
        cluster_user = get_object_or_404(ClusterUser, id=user_id)
        quota = cluster.get_quota(cluster_user)
        data = {'user':user_id}
        if quota:
            data.update(quota)
    else:
        return render_404(request, 'User was not found')
    
    form = QuotaForm(data)
    return render_to_response("cluster/quota.html", \
                        {'form':form, 'cluster':cluster, 'user_id':user_id}, \
                        context_instance=RequestContext(request))


class EditClusterForm(forms.ModelForm):
    confirm_password = forms.CharField(required=False, widget=forms.PasswordInput)
    class Meta:
        model = Cluster
        widgets = {
            'password' : forms.PasswordInput(),
            'confirm_password' : forms.PasswordInput(),
        }
        
    
    
    def clean(self):
        self.cleaned_data = super(EditClusterForm, self).clean()
        data = self.cleaned_data
        host = data.get('hostname', None)
        user = data.get('username', None)
        new = data.get('password', None)
        confirm = data.get('confirm_password', None)
        
        # Automatically set the slug on cluster creation
        if not host:
            msg = 'Enter a hostname'
            self._errors['hostname'] = self.error_class([msg])
            
        if user: 
            if not new:
                if 'password' in data: del data['password']
                msg = 'Enter a password'
                self._errors['password'] = self.error_class([msg])
            
            if not confirm:
                if 'confirm_password' in data: del data['confirm_password']
                msg = 'Confirm new password'
                self._errors['confirm_password'] = self.error_class([msg])
            
            if new and confirm and new != confirm:
                del data['password']
                del data['confirm_password']
                msg = 'Passwords do not match'
                self._errors['password'] = self.error_class([msg])
                
        elif new or confirm:
            msg = 'Enter a username'
            self._errors['username'] = self.error_class([msg])
            
            if not new:
                if 'password' in data: del data['password']
                msg = 'Enter a password'
                self._errors['password'] = self.error_class([msg])
                
            if not confirm:
                if 'confirm_password' in data: del data['confirm_password']
                msg = 'Confirm new password'
                self._errors['confirm_password'] = self.error_class([msg])
            
            if new and confirm and new != confirm:
                del data['password']
                del data['confirm_password']
                msg = 'Passwords do not match'
                self._errors['password'] = self.error_class([msg])
            
                
        if 'hostname' in data and data['hostname'] and 'slug' not in data:
            data['slug'] = slugify(data['hostname'].split('.')[0])
            del self._errors['slug']
        
        return data
