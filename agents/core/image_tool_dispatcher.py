"""Server-owned image proposal routing; cloud execution stays with its worker."""

from copy import deepcopy

from .action_origin import current_action_origin
from .image_generation_runtime import INPUT_SCHEMA as LOCAL_SCHEMA
from .media_backends import deepinfra_image, krea_image, openrouter_image, xai_image
from .media_backends.codex_image import normalize_request as normalize_codex
from .media_backends.fal_image import normalize_request as normalize_fal
from .media_backends.openai_image import IMAGE2_TIERS, MODEL, SIZES, normalize_request
from .tool_rpc import ToolRPCValidationError

INPUT_SCHEMA = deepcopy(LOCAL_SCHEMA)
INPUT_SCHEMA['properties'].update({
    'cloud': {'type': 'boolean', 'description': 'Explicit approved cloud proposal using provider billing or configured Codex account; default false.'},
    'size': {'type': 'string', 'enum': sorted(SIZES)},
    'quality': {'type': 'string', 'enum': ['auto', 'low', 'medium', 'high']},
    'aspect_ratio_exact': {'type': 'string', 'maxLength': 16},
    'resolution': {'type': 'string', 'enum': ['512', '1K', '2K', '1k', '2k']},
    'background': {'type': 'string', 'enum': ['auto', 'opaque', 'transparent']},
    'output_compression': {'type': 'integer', 'minimum': 0, 'maximum': 100},
    'n': {'type': 'integer', 'enum': [1]},
    'aspect_ratio': {'type': 'string', 'enum': ['square', 'landscape', 'portrait']},
    'creativity': {'type': 'string', 'enum': ['raw', 'low', 'medium', 'high']},
    'resume_task_id': {'type': 'integer', 'minimum': 1, 'maximum': 2**63 - 1,
                       'description': 'Krea only: fresh approval to poll an existing job; prompt must be empty.'},
    'enhance_task_id': {'type': 'integer', 'minimum': 1, 'maximum': 2**63 - 1,
                        'description': 'Krea only: fresh approval to enhance a completed image; prompt must be empty.'},
    'refresh_catalog': {'type': 'boolean', 'description': 'DeepInfra only: approve reading its model catalog; prompt must be empty.'},
    'image_style_references': {'type': 'array', 'minItems': 1, 'maxItems': 10, 'items': {
        'anyOf': [{'type': 'string', 'maxLength': 2048}, {'type': 'object',
            'properties': {'url': {'type': 'string', 'maxLength': 2048},
                           'strength': {'type': 'number', 'minimum': -2, 'maximum': 2}},
            'required': ['url', 'strength'], 'additionalProperties': False}],
    }, 'description': 'Krea only: explicit HTTPS style URL or URL/strength object; style-guided generation, not editing.'},
})
INPUT_SCHEMA['properties']['prompt']['minLength'] = 0
INPUT_SCHEMA['properties']['backend']['description'] = 'Local configured backend, or openai/openai-codex/fal/openrouter/krea/xai/deepinfra with cloud=true.'
INPUT_SCHEMA['properties']['model']['maxLength'] = 256
INPUT_SCHEMA['properties']['model']['description'] = f'Local checkpoint, {MODEL}, OpenAI/Codex GPT Image2 tier, or offered FAL/OpenRouter/Krea/xAI/DeepInfra model.'
INPUT_SCHEMA['properties']['references'] = {
    'type': 'array', 'items': {'type': 'string', 'maxLength': 2048},
    'minItems': 1, 'maxItems': 16, 'uniqueItems': True,
    'description': 'Local: up to 4 artifact IDs. OpenAI/Codex/OpenRouter/xAI: model-bounded generated artifact IDs. FAL: model-bounded fal.media URLs. Krea uses image_style_references; DeepInfra is text-only.',
}

_FAL_OPTIONS = {'backend', 'model', 'size', 'seed', 'steps', 'references'}
_PROVIDER_OPTIONS = {
    'openrouter': {'backend', 'model', 'size', 'references', 'aspect_ratio_exact',
                   'resolution', 'quality', 'background', 'output_compression', 'seed', 'n'},
    'krea': {'backend', 'model', 'size', 'aspect_ratio', 'creativity', 'seed', 'image_style_references'},
    'xai': {'backend', 'model', 'size', 'references', 'resolution', 'quality', 'n'},
    'deepinfra': {'backend', 'model', 'size', 'aspect_ratio', 'references', 'n'},
}


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
            if 'enhance_task_id' in args:
                raise ToolRPCValidationError('unsupported_cloud_image_option')
            local = {key: value for key, value in args.items() if key != 'cloud'}
            return self.local.preflight(local)
        if self.approved_task() is not None:
            raise ToolRPCValidationError('cloud_worker_required')
        if 'resume_task_id' in args or 'enhance_task_id' in args or 'refresh_catalog' in args:
            if set(args) == {'cloud', 'backend', 'prompt', 'enhance_task_id'}:
                task_id = args['enhance_task_id']
                valid = args['backend'] == 'krea' and type(task_id) is int and 1 <= task_id < 2**63
            elif set(args) == {'cloud', 'backend', 'prompt', 'resume_task_id'}:
                task_id = args['resume_task_id']
                valid = args['backend'] == 'krea' and type(task_id) is int and 1 <= task_id < 2**63
            else:
                valid = (set(args) == {'cloud', 'backend', 'prompt', 'refresh_catalog'}
                         and args.get('backend') == 'deepinfra' and args.get('refresh_catalog') is True)
            if not valid or args.get('prompt') != '':
                raise ToolRPCValidationError('unsupported_cloud_image_option')
            return dict(args)
        if args.get('backend') in _PROVIDER_OPTIONS:
            selected = args['backend']
            allowed = _PROVIDER_OPTIONS[selected]
            if set(args) - (allowed | {'cloud', 'prompt'}):
                raise ToolRPCValidationError('unsupported_cloud_image_option')
            options = {key: args[key] for key in allowed if key in args}
            try:
                module = {'openrouter': openrouter_image, 'krea': krea_image,
                          'xai': xai_image, 'deepinfra': deepinfra_image}[selected]
                extra = {}
                if selected == 'deepinfra':
                    runtime = self.cloud_runtime()
                    if runtime is None:
                        raise ValueError('cloud runtime unavailable')
                    extra['catalog'] = runtime.catalog()
                body = module.normalize_request(args.get('prompt'), options, **extra)
                if body.get('resolution') == '4K':
                    raise ValueError('unsupported artifact resolution')
            except (ValueError, TypeError):
                raise ToolRPCValidationError('unsupported_cloud_image_option') from None
            return {'cloud': True, 'prompt': body['prompt'], **options,
                    'model': body['model'], 'size': body['size']}
        if args.get('backend') == 'fal':
            if set(args) - (_FAL_OPTIONS | {'cloud', 'prompt'}):
                raise ToolRPCValidationError('unsupported_cloud_image_option')
            try:
                body = normalize_fal(args.get('prompt'), {
                    key: args[key] for key in _FAL_OPTIONS if key in args
                })
            except (ValueError, TypeError):
                raise ToolRPCValidationError('unsupported_cloud_image_option') from None
            return {'cloud': True, 'backend': 'fal', 'prompt': body['prompt'], **{
                key: body[key] for key in _FAL_OPTIONS - {'backend'} if key in body
            }}
        if args.get('backend') == 'openai-codex':
            if set(args) - {'cloud', 'prompt', 'backend', 'model', 'size', 'references'}:
                raise ToolRPCValidationError('unsupported_cloud_image_option')
            try:
                body = normalize_codex(args.get('prompt'), {
                    key: args[key] for key in ('model', 'size', 'references') if key in args
                })
            except (ValueError, TypeError):
                raise ToolRPCValidationError('unsupported_cloud_image_option') from None
            return {'cloud': True, 'backend': 'openai-codex', **body}
        if set(args) - {'cloud', 'prompt', 'backend', 'model', 'size', 'quality', 'references'}:
            raise ToolRPCValidationError('unsupported_cloud_image_option')
        if args.get('backend', 'openai') != 'openai':
            raise ToolRPCValidationError('unsupported_cloud_image_backend')
        try:
            refs = args.get('references', [])
            if refs and (args.get('model', MODEL) not in IMAGE2_TIERS or
                         not isinstance(refs, list) or len(refs) > 16 or
                         any(not isinstance(ref, str) or len(ref) != 32 or
                             any(ch not in '0123456789abcdef' for ch in ref) for ref in refs)):
                raise ValueError('invalid image references')
            body = normalize_request(args.get('prompt'), {
                key: args[key] for key in ('model', 'size', 'quality') if key in args
            })
        except ValueError:
            raise ToolRPCValidationError('unsupported_cloud_image_option') from None
        return {'cloud': True, 'backend': 'openai', 'prompt': body['prompt'],
                'model': args.get('model', MODEL), 'size': body['size'],
                **({'quality': body['quality']} if args.get('model', MODEL) == MODEL else {}),
                **({'references': refs} if refs else {})}

    def intake(self, actor, args):
        if args.get('cloud') is not True:
            if 'enhance_task_id' in args:
                raise ToolRPCValidationError('unsupported_cloud_image_option')
            return self.local.intake(actor, args)
        runtime = self.cloud_runtime()
        if runtime is None:
            raise ToolRPCValidationError('cloud_image_unavailable')
        try:
            if 'enhance_task_id' in args:
                return runtime.enhance(args['enhance_task_id'], current_action_origin(), actor=actor)
            if 'resume_task_id' in args:
                return runtime.resume(args['resume_task_id'], current_action_origin(), actor=actor)
            if args.get('refresh_catalog') is True:
                return runtime.refresh_catalog('deepinfra', current_action_origin(), actor=actor)
            return runtime.submit(args['prompt'], {
                key: args[key] for key in
                (_PROVIDER_OPTIONS[args['backend']] if args.get('backend') in _PROVIDER_OPTIONS else
                 _FAL_OPTIONS if args.get('backend') == 'fal' else
                 {'backend', 'model', 'size', 'references'} if args.get('backend') == 'openai-codex' else
                 {'backend', 'model', 'size', 'quality', 'references'})
                if key in args
            }, current_action_origin(), actor=actor)
        except Exception:
            # Provider configuration and prompt screening failures are private.
            # An ambiguous enqueue must never trigger another submission here.
            raise ToolRPCValidationError('cloud_image_proposal_refused') from None

    async def execute(self, args):
        if 'cloud' in args:
            return {'status': 'failed', 'reason': 'cloud_worker_required'}
        return await self.local.execute(args)
