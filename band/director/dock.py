from pathlib import Path
import docker
# from aiofiles import os
import os
from prodict import Prodict

from .. import logger

BASE_IMG_TMPL = 'rst/{}'
USER_IMG_TMPL = 'user/srv-{}'
SHORT_FIEL_LIST = ['short_id', 'name', 'status']

LINBAND = 'inband'
LPORTS = 'ports'
LDELIM = ':'


def pick(d, *keys):
    return {k: (getattr(d, k) if hasattr(d, k) else d[k]) for k in keys}


class Labels(dict):
    @property
    def marked(self):
        return bool(self.get(LINBAND, False))

    def mark(self):
        self[LINBAND] = 'yes'
        return self

    @property
    def ports(self):
        pstr = self.get(LPORTS, None)
        return [int(p) for p in pstr.split(LDELIM)] if bool(pstr) else []

    @ports.setter
    def ports(self, plist):
        self[LPORTS] = LDELIM.join([str(p) for p in plist])

    def __getattr__(self, attr):
        return self.get(attr)


class Dock():
    """
    Docker api found at https://docs.docker.com/engine/api/v1.24/#31-containers
    """

    def __init__(self, bind_addr, images_path, default_image, container_env, **kwargs):

        self.dc = docker.from_env()
        self.initial_ports = list(range(8900, 8999))
        self.available_ports = list(self.initial_ports)

        self.bind_addr = bind_addr
        self.images_path = images_path
        self.default_image = default_image
        self.container_env = container_env

        # self.params = kwargs
        # self.params.update(dockopts)

        print(os.stat(images_path))

        self.images_path = Path(images_path).resolve().as_posix()
        self.inspect_containers()

    def inspect_containers(self):
        containers = self.ls().values()

        for container in containers:
            self.inspect_container(container)

    def inspect_container(self, container):
        logger.info('inspecting container {0.name} '.format(container))
        lbs = Labels(container.labels)
        for port in lbs.ports:
            self.allocate_port(port)

    def ls(self):
        containers = self.dc.containers.list(all=True,
                                             filters={'label': LINBAND})
        return {c.name: c for c in containers}

    def containers_list(self):
        return list([pick(c, *SHORT_FIEL_LIST) for c in self.ls().values()])

    def get(self, name):
        for cn, c in self.ls().items():
            if cn == name:
                return c

    def allocate_port(self, port=None):
        if port:
            if port in self.available_ports:
                logger.info("port {} excluded".format(port))
                self.available_ports.remove(port)
            else:
                logger.info(
                    "hohoho smth wrong {}: {}".format(port, type(port)))
        else:
            port = self.available_ports.pop()
            logger.info("allocated port {}".format(port))

        return port

    def remove_container(self, name):
        self.stop_container(name)

        containers = self.ls()

        if name in list(containers.keys()):
            logger.info("removing container {}".format(name))
            containers[name].remove()

        return True

    def stop_container(self, name):
        containers = self.ls()

        if name in list(containers.keys()):
            containers[name].stop()
            logger.info("stopping container {}".format(name))
            return True

    def ping(self, name):
        return 'not implemented'

    def build_image(self, base, name):
        
        # # Base images
        # params = {
        #     'path': self.images_path,
        #     'tag': BASE_IMG_TMPL.format(base),
        #     'labels': Labels()
        # }
        # logger.info("building base image {tag} from {path}".format(**params))
        # self.dc.images.build(**params)

        params = {
            'path': self.images_path,
            'tag': USER_IMG_TMPL.format(name),
            'labels': Labels()
        }
        logger.info("building service image {tag} from {path}".format(**params))
        
        return self.dc.images.build(**params)[0]


    def run_container(self, name, params):

        self.remove_container(name)

        logger.info("building image for {}".format(name))

        img = self.build_image(self.images_path, name)
        attrs = Prodict.from_dict(img.attrs)

        ports = {}
        allocated = []
        for port in attrs.Config.ExposedPorts or {}:
            aport = self.allocate_port()
            allocated.append(aport)
            ports[port] = (self.bind_addr, aport)

        params = {
            'name': name,
            'hostname': name,
            'ports': ports,
            'labels': {'inband': 'yes', 'ports': ";".join([str(v) for v in allocated])},
            'environment': self.container_env,
            'detach': True,
            'auto_remove': False
        }

        logger.info(
            'starting container {name}. Exposing ports: {labels[ports]}'.format(**params))
        container = self.dc.containers.run(img.tags[0], **params)

        logger.info(
            'started container {0.name} [{0.short_id}]'.format(container))
        return pick(container, 'short_id', 'name')
