# coding=utf-8
#    Copyright 2012 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_config import cfg
from oslo_log import log as logging
from oslo_middleware import base
from oslo_middleware import request_id
import webob.dec
import webob.exc

from neutron import context

LOG = logging.getLogger(__name__)


class NeutronKeystoneContext(base.ConfigurableMiddleware):
    """Make a request context from keystone headers."""

    @webob.dec.wsgify
    def __call__(self, req):
        # Determine the user ID
        user_id = req.headers.get('X_USER_ID')
        if not user_id:
            LOG.debug("X_USER_ID is not found in request")
            return webob.exc.HTTPUnauthorized()

        # Determine the tenant
        tenant_id = req.headers.get('X_PROJECT_ID')

        # Suck out the roles
        roles = [r.strip() for r in req.headers.get('X_ROLES', '').split(',')]

        # Human-friendly names
        tenant_name = req.headers.get('X_PROJECT_NAME')
        user_name = req.headers.get('X_USER_NAME')

        # Use request_id if already set
        req_id = req.environ.get(request_id.ENV_REQUEST_ID)

        # Get the auth token
        auth_token = req.headers.get('X_AUTH_TOKEN',
                                     req.headers.get('X_STORAGE_TOKEN'))

        # Create a context with the authentication data
        ctx = context.Context(user_id, tenant_id, roles=roles,
                              user_name=user_name, tenant_name=tenant_name,
                              request_id=req_id, auth_token=auth_token)

        # Inject the context...
        req.environ['neutron.context'] = ctx

        return self.application


def pipeline_factory(loader, global_conf, **local_conf):
    """Create a paste pipeline based on the 'auth_strategy' config option."""
    # 依据鉴权策略（auth_strategy），创建一个paste pipeline
    '''
        字典 伪代码
        local_conf {
            noauth: cors ...... extensions neutronapiapp_v2_0
            keystone: cors ...... keystonecontext extensions neutronapiapp_v2_0
        }
    '''
    # 根据配置文件读取其中一个值，假如是keystone
    pipeline = local_conf[cfg.CONF.auth_strategy]
    # pipeline = "cors ...... keystonecontext extensions neutronapiapp_v2_0"
    # 讲一个字符串分解为一个list
    # pipeline = {"cors", ... , "keystonecontext", "extensions",
    # "neutronapiapp_v2_0}
    pipeline = pipeline.split()
    # 调用loader这个对象，获取一系列的filter
    filters = [loader.get_filter(n) for n in pipeline[:-1]]
    # filter = {app_cors, ..., app_keystonecontext, app_ext}
    # 加载最后一个app，执行完后app的值为（伪代码） app = app_v2.0
    # 根据前面的分析，这里的app就是Core Service的WSGI Application，
    # 也就是class APIRouter的实例对象
    app = loader.get_app(pipeline[-1])
    # 讲filters倒序排列
    # 下面代码实际是讲app_v2.0外面一层一层加上filter，首先加上app_ext，然后是
    # app_keystonecontext，最后是app_cors。这也是倒序排列的原因，首先要加最内层的filter
    filters.reverse()
    # 这个循环中，第一个filter就是Extension Service的
    # WSGI Application的工厂函数，也就是_factory(app)的函数
    # 所以，这里的参数app就是class APIRouter的实例对象
    for filter in filters:
        app = filter(app)
    return app
