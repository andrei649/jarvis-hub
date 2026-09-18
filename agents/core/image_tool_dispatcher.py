"""Server-owned image proposal routing; cloud execution stays with its worker."""

from copy import deepcopy

from .action_origin import current_action_origin
from .image_generation_runtime import INPUT_SCHEMA as LOCAL_SCHEMA
from .media_backends.openai_image import MODEL, SIZES, normalize_request
from .tool_rpc import ToolRPCValidationError

INPUT_SCHEMA = deepcopy(LOCAL_SCHEMA)
INPUT_SCHEMA['properties'].update({
    'cloud': {'type': 'boolean', 'description': 'Explicit paid cloud proposal; default false.'},
    'size': {'type': 'string', 'enum': sorted(SIZES)},
    'quality': {'type': 'string', 'enum': ['low', 'medium', 'high']},
})
INPUT_SCHEMA['properties']['backend']['description'] = 'Local configured backend, or openai with cloud=true.'
INPUT_SCHEMA['properties']['model']['description'] = f'Local checkpoint, or {MODEL} with cloud=true.'


class ImageToolDispatcher:
    def __init__(self, local, *, cloud_runtime, approved_task):
        self.local = local
        self.cloud_runtime = cloud_runtime
        self.approved_task = approved_task

    def preflight(self, args):
        cloud = args.get('cloud', False)
        if type(cloud) is not bool:
            raise ToolRPCValidationError('invalid_cloud_selector')
        if not cloud:
            local = {key: value for key, value in args.items() if key != 'cloud'}
            return self.local.preflight(local)
        if self.approved_task() is not None:
            raise ToolRPCValidationError('cloud_worker_required')
        if set(args) - {'cloud', 'prompt', 'backend', 'model', 'size', 'quality'}:
            raise ToolRPCValidationError('unsupported_cloud_image_option')
        if args.get('backend', 'openai') != 'openai':
            raise ToolRPCValidationError('unsupported_cloud_image_backend')
        try:
            body = normalize_request(args.get('prompt'), {
                key: args[key] for key in ('model', 'size', 'quality') if key in args
            })
        except ValueError:
            raise ToolRPCValidationError('unsupported_cloud_image_option') from None
        return {'cloud': True, 'prompt': body['prompt'], **{
            key: body[key] for key in ('model', 'size', 'quality')
        }}

    def intake(self, actor, args):
        if args.get('cloud') is not True:
            return self.local.intake(actor, args)
        runtime = self.cloud_runtime()
        if runtime is None:
            raise ToolRPCValidationError('cloud_image_unavailable')
        try:
            return runtime.submit(args['prompt'], {
                key: args[key] for key in ('model', 'size', 'quality')
            }, current_action_origin(), actor=actor)
        except Exception:
            # Provider configuration and prompt screening failures are private.
            # An ambiguous enqueue must never trigger another submission here.
            raise ToolRPCValidationError('cloud_image_proposal_refused') from None

    async def execute(self, args):
        if 'cloud' in args:
            return {'status': 'failed', 'reason': 'cloud_worker_required'}
        return await self.local.execute(args)
