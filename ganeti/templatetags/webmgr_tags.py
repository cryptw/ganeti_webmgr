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

from math import log10
import re
import json as json_lib

from django import template
from django.template import Library, Node, TemplateSyntaxError
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

from ganeti.models import Cluster


register = Library()

"""
These filters were created specifically
for the Ganeti Web Manager project
"""
@register.inclusion_tag('virtual_machine/vmfield.html')
def vmfield(field):
    return {'field':field}

@register.filter
@stringfilter
def truncate(value, count):
    """
    Truncates value after specified number of chars
    """
    if count < len(value):
        return value[:count] + " ..."
    return value

@register.filter
@stringfilter
def ssh_comment(value):
    """
    If value is good SSH public key, then returns the user@hostname for who
    the key is set.
    """
    pos1 = value.find(" ")
    pos2 = value[(pos1+1):].find(" ")
    if pos2 > -1:
        return value[pos1+pos2+2:]
    return value

@register.filter
@stringfilter
def ssh_keytype(value):
    """
    If value is good SSH public key, then returns the user@hostname for who
    the key is set.
    """
    pos = value.find(" ")
    if pos > -1:
        return value[:pos]
    return value

@register.filter
@stringfilter
def ssh_keypart_truncate(value, count):
    try:
        pos0 = value.find(" ")
        pos1 = value[(pos0+1):].find(" ") + pos0
        if (pos0==-1 or pos1==-1) or (pos0==pos1):
            raise BaseException
        value = value[pos0+1:pos1+1]
        
        if len(value) > count:
            value = "%s ... %s" % (value[:(count/2)], value[(-count/2):])
    except BaseException:
        pass
    finally:
        return value

"""
These filters were taken from Russel Haering's GanetiWeb project
"""

@register.filter
@stringfilter
def render_node_status(status):
    if status:
        return "Offline"
    else:
        return "Online"


@register.filter
@stringfilter
def render_instance_status(status):
    return status.replace('ADMIN_', '', 1)\
                 .replace('ERROR_', '', 1)\
                 .capitalize()


@register.filter
@stringfilter
def render_storage(value):
    amount = float(value)
    if amount >= 1024:
        return "%.2f GB" % (amount/1024)
    else:
        return "%d MB" % int(amount)


@register.filter
def quota(cluster_user, cluster):
    """
    Returns the quota for user/cluster combination.
    """
    return cluster.get_quota(cluster_user)


@register.filter
def cluster_nodes(cluster, bulk=False):
    """
    Helper tag for passing parameter to cluster.nodes()
    """
    return cluster.nodes(bulk)


@register.filter
def cluster_admin(user):
    """
    Returns whether the user has admin permission on any Cluster
    """
    return user.has_any_perms(Cluster, ['admin'])


def format_part_total(part, total):
    """
    Pretty-print a quantity out of a given total.
    """

    total = float(total) / 1024
    part = float(part) / 1024
    return "%.*f / %.*f" % (
        int(3 - log10(part)), part, int(3 - log10(total)), total)

@register.simple_tag
def node_memory(node):
    """
    Pretty-print a memory quantity, in GiB, with significant figures.
    """

    return format_part_total(node["mfree"], node["mtotal"])


@register.simple_tag
def node_disk(node):
    """
    Pretty-print a disk quantity, in GiB, with significant figures.
    """

    return format_part_total(node["dfree"], node["dtotal"])


@register.filter
def json(obj):
    return mark_safe(json_lib.dumps(obj))


@register.tag
def get_nics(parser, token):
    try:
        tag_name, arg = token.contents.split(None, 1)
    except ValueError:
        raise TemplateSyntaxError, "%r tag requires arguments" % token.contents.split()[0]
    m = re.search(r'(\w+) as (\w+)', arg)
    if not m:
        raise TemplateSyntaxError, "%r tag had invalid arguments" % tag_name
    instance_name, res_name = m.groups()
    return NicsNode(instance_name, res_name)


class NicsNode(Node):
    def __init__(self, instance_name, res_name):
        self.instance_name = instance_name
        self.res_name = res_name

    def render(self, context):
        instance = context[self.instance_name]
        context[self.res_name] = zip(instance['nic.bridges'], instance['nic.ips'], instance['nic.links'],
                                     instance['nic.macs'], instance['nic.modes'])
        return ''


@register.tag
def get_by_name(parser, token):
    try:
        tag_name, arg = token.contents.split(None, 1)
    except ValueError:
        raise TemplateSyntaxError, "%r tag requires arguments" % token.contents.split()[0]
    m = re.search(r'\s*(.+)\s+"(.+)"\s+as\s+(\w+)', arg)
    if not m:
        raise TemplateSyntaxError, "%r tag had invalid arguments" % tag_name
    item_name, attr_name, res_name = m.groups()
    return GetterNode(item_name, attr_name, res_name)


class GetterNode(Node):
    def __init__(self, item_name, attr_name, res_name):
        self.item_name = item_name
        self.attr_name = attr_name
        self.res_name = res_name

    def render(self, context):
        context[self.res_name] = context[self.item_name][self.attr_name]
        return ''

# These filters were created by Corbin Simpson IN THE NAME OF AWESOME!
# Just kidding. Created for ganeti-webmgr at Oregon State University.

@register.filter
@stringfilter
def abbreviate_fqdn(value):
    return value.split(".")[0]

@register.filter
@stringfilter
def render_os(os):
    try:
        t, flavor = os.split("+", 1)
        flavor = " ".join(i.capitalize() for i in flavor.split("-"))
        return mark_safe("%s (<em>%s</em>)" % (flavor, t))
    except ValueError:
        return mark_safe("<em>Unknown or invalid OS</em>")
