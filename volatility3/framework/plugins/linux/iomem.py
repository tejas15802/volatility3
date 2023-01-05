# This file is Copyright 2023 Volatility Foundation and licensed under the Volatility Software License 1.0
# which is available at https://www.volatilityfoundation.org/license/vsl-v1.0
#
import logging
from typing import List

from volatility3.framework import renderers, interfaces, exceptions
from volatility3.framework.configuration import requirements
from volatility3.framework.objects import utility
from volatility3.framework.renderers import format_hints

vollog = logging.getLogger(__name__)


class IOMem(interfaces.plugins.PluginInterface):
    """Generates an output similar to /proc/iomem on a running system."""

    _required_framework_version = (2, 0, 0)

    @classmethod
    def get_requirements(cls) -> List[interfaces.configuration.RequirementInterface]:
        return [
            requirements.ModuleRequirement(
                name="kernel",
                description="Linux kernel",
                architectures=["Intel32", "Intel64"],
            )
        ]

    @classmethod
    def parse_resource(
        cls,
        context: interfaces.context.ContextInterface,
        vmlinux_module_name: str,
        resource_offset: int,
        seen: set = set(),
        depth: int = 0,
    ):
        """Recursively parse from a root resource to find details about all related resources.

        Args:
            context: The context to retrieve required elements (layers, symbol tables) from
            vmlinux_module_name: The name of the kernel module on which to operate
            resource_offset: The offset to the resouce to be parsed
            seen: The set of resource offsets that have already been parsed
            depth: How deep into the resource structure we are

        Yields:
            Each row of output
        """
        # create the resource object
        vmlinux = context.modules[vmlinux_module_name]
        resource = vmlinux.object("resource", resource_offset)

        # extract the information required for this resource
        name = utility.pointer_to_string(resource.name, 128)
        start = format_hints.Hex(resource.start)
        end = format_hints.Hex(resource.end)

        # mark this resource as seen in the seen set. Normally this should not be needed but will protect
        # against possible infinite loops. Warn the user if an infinite loop would have happened.
        if resource_offset in seen:
            vollog.warning(
                f"The resource object at {resource_offset:#x} '{name}' has already been processed, "
                "this should not normally occur. No further results from related resources will be "
                "displayed to protect against infinite loops."
            )
            return None
        else:
            seen.add(resource_offset)

        # yield information on this resource
        yield depth, (name, start, end)

        # process child resource if this exists
        if resource.child != 0:
            yield from cls.parse_resource(
                context,
                vmlinux_module_name,
                resource.child,
                seen,
                depth + 1,
            )

        # process sibling resource if this exists
        if resource.sibling != 0:
            yield from cls.parse_resource(
                context,
                vmlinux_module_name,
                resource.sibling,
                seen,
                depth,
            )

    def _generator(self):
        """Generates an output similar to /proc/iomem on a running system

        Args:
            None

        Yields:
            Each row of output using the parse_resource function
        """

        # get the kernel module from the current context
        vmlinux_module_name = self.config["kernel"]
        vmlinux = self.context.modules[vmlinux_module_name]

        # check that the iomem_resource symbol exists
        # normally exported in /kernel/resource.c
        try:
            iomem_root_offset = vmlinux.get_absolute_symbol_address("iomem_resource")
        except exceptions.SymbolError:
            iomem_root_offset = None

        # error if 'iomem_resource' is not found
        if not iomem_root_offset:
            raise TypeError(
                "This plugin requires the iomem_resource structure. This structure is not present in the supplied symbol table. This means you are either analyzing an unsupported kernel version or that your symbol table is corrupt."
            )

        # error if type 'resource' is not found
        if not vmlinux.has_type("resource"):
            raise TypeError(
                "This plugin requires the resource type. This type is not present in the supplied symbol table. This means you are either analyzing an unsupported kernel version or that your symbol table is corrupt."
            )

        # recursively parse the resources starting from the root resource at 'iomem_resource'
        yield from self.parse_resource(
            self.context, vmlinux_module_name, iomem_root_offset
        )

    def run(self):
        columns = [
            ("NAME", str),
            ("START", format_hints.Hex),
            ("END", format_hints.Hex),
        ]
        return renderers.TreeGrid(columns, self._generator())
