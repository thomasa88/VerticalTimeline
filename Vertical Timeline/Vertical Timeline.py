#Author-Thomas Axelsson
#Description-Provides a vertical timeline.

# Need to use Visual Studio Code Python extension version 2019.9.34911
# to be able to debug with Fusion.. (2020-07-23)

import adsk.core, adsk.fusion, adsk.cam, traceback

import json
import os

# global set of event handlers to keep them referenced for the duration of the command
handlers = []

ui = None
app = None
onCommandTerminated = None
enabled = False

# Occurrence types
OCCURRENCE_GENERAL_COMP = 0
OCCURRENCE_COPY_COMP = 1
OCCURRENCE_SHEET_METAL = 2
OCCURRENCE_BODIES_COMP = 3

def get_timeline():
    product = app.activeProduct
    if product is None or product.classType() != 'adsk::fusion::Design':
        print("get_timeline: Product not ready")
        return None
    
    design = adsk.fusion.Design.cast(product)

    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        return design.timeline
    else:
        return None

def get_occurrence_type(item):
    if item.name.startswith('CopyPaste '):
        return OCCURRENCE_COPY_COMP
    elif hasattr(item.entity, 'bRepBodies'):
        if item.entity.bRepBodies.count == 0:
            return OCCURRENCE_SHEET_METAL
        else:
            return OCCURRENCE_BODIES_COMP
    else:
        return OCCURRENCE_GENERAL_COMP

OCCURRENCE_RESOURCE_MAP = {
    OCCURRENCE_GENERAL_COMP: 'Fusion/UI/FusionUI/Resources/Modeling/BooleanNewComponent',
    OCCURRENCE_COPY_COMP: 'Fusion/UI/FusionUI/Resources/Assembly/CopyPasteInstance',
    OCCURRENCE_SHEET_METAL: 'Neutron/UI/Base/Resources/Browser/ComponentSheetMetal',
    OCCURRENCE_BODIES_COMP: 'Fusion/UI/FusionUI/Resources/Assembly/CreateComponentFromBody',
}

FEATURE_RESOURCE_MAP = {
    # This list is hand-crafted. Please respect the work put into this list and
    # retain the Copyright and License stanzas if you copy it.
    # Helpful toosl: ImageSorter, Process Monitor.
    'LoftFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/loft' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/loft',
    'Sketch': 'Fusion/UI/FusionUI/Resources/sketch/Sketch_feature',
    'ExtrudeFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/extrude' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/extrude',
    'Occurrence': lambda i: OCCURRENCE_RESOURCE_MAP[get_occurrence_type(i)],
    'BoundaryFillFeature': 'Fusion/UI/FusionUI/Resources/surface/surface_sculpt',
    'SurfaceDeleteFaceFeature': 'Fusion/UI/FusionUI/Resources/modify/surface_delete',
    'CombineFeature': 'Fusion/UI/FusionUI/Resources/modify/combine',
    'RevolveFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/revolve' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/revolve',
    'SweepFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/sweep' if i.entity.isSolid else 'Fusion/UI/FusionUI/Resources/surface/sweep',
    'RibFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/rib',
    'WebFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/web',
    'BoxFeature': lambda i: 'Fusion/UI/FusionUI/Resources/solid/primitive_box',
    'CylinderFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_cylinder',
    'SphereFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_sphere',
    'TorusFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_torus',
    'CoilFeature': 'Fusion/UI/FusionUI/Resources/solid/Coil',
    'PipeFeature': 'Fusion/UI/FusionUI/Resources/solid/primitive_pipe',
    'RectangularPatternFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_rectangular',
    'CircularPatternFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_circular',
    'PathPatternFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_path',
    'MirrorFeature': 'Fusion/UI/FusionUI/Resources/pattern/pattern_mirror',
    'ThickenFeature': 'Fusion/UI/FusionUI/Resources/surface/thicken',
}

def get_feature_image(item):
    entity = item.entity
    fusionType = entity.classType().replace('adsk::fusion::', '')
    match = FEATURE_RESOURCE_MAP.get(fusionType)
    if callable(match):
        match = match(item)

    if not match:
        # Image not mapped
        match = 'Fusion/UI/FusionUI/Resources/finish/finishX'
    
    return get_image_path(match)

def get_image_path(subpath):
    path = f'{get_product_deploy_folder()}/{subpath}/16x16.png'
    if os.path.exists(path):
        return path
    else:
        print(f'File does not exist: {path}')
        return None

_resFolder = None
def get_resource_folder():
    global _resFolder
    if not _resFolder:
        _resFolder = ui.workspaces.itemById('FusionSolidEnvironment').resourceFolder.replace('/Environment/Model', '')
    return _resFolder

def get_product_deploy_folder():
    return get_resource_folder().replace('/Fusion/UI/FusionUI/Resources', '')

def find_commands(substring):
    return [c.id for c in ui.commandDefinitions if substring in c.id.lower()]

def find_commands_by_resource_folder(folder):
    commands = []
    for c in ui.commandDefinitions:
        try:
            if folder in c.resourceFolder.lower():
                commands.append(c.id)
        except:
            pass
    return commands

# ui.commandDefinitions.itemById('').resourceFolder
# design.rootComponent.allOccurrences[0].component.sketches

features_cache = []
def invalidate(send=True, emptyTimeline=False):
    global features_cache

    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')

    if not palette:
        return

    if emptyTimeline:
        features = []
    else:
        timeline = get_timeline()
        if timeline is not None:
            features = get_features(timeline)
        else:
            features = []
    features_cache = features

    action = 'setTimeline'
    data = features
    if not send:
        # Cannot do sendInfoToHTML inside the HTML event handler. We either have to use htmlArgs.returnData or
        # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
        html_command = {'action': 'setTimeline', 'data': data}
        return html_command
    else:
        palette.sendInfoToHTML('setTimeline', json.dumps(data))

def get_features(timeline_container, id_base=''):
    features = []
    for i, item in enumerate(timeline_container):
        classType = item.classType()
        feature = {
            'id': f'{id_base}{i}',
            'name': item.name,
            'suppressed': item.isSuppressed or item.isRolledBack,
            }
        if not item.isGroup:
            feature['type'] = item.entity.classType().split('::')[-1]
            feature['image'] = get_feature_image(item)

            if feature['type'] == 'Occurrence':
                # Fusion uses a space separator for the timeline object name, but sometimes the first part is empty.
                # Strip the whitespace to make the list cleaner.
                feature['name'] = feature['name'].lstrip()
                if get_occurrence_type(item) != OCCURRENCE_BODIES_COMP:
                    # Name is a read-only instance variant of the component's name
                    # Let the user modify the component's name instead
                    feature['component-name'] = item.entity.component.name
        else:
            feature['type'] = 'GROUP'
            feature['image'] = get_image_path('Fusion/UI/FusionUI/Resources/Timeline/GroupFeature')
            feature['children'] = get_features(item, feature['id'] + '-')
        features.append(feature)
    return features

def get_item_by_id_string(id_string):
    item = get_timeline()
    for i in id_string:
        item = item[int(i)]
    return item

def error_catcher_wrapper(func):
    def catcher(self, args):
        try:
            func(args)
        except:
            print('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))
            if ui:
                ui.messageBox(f'Vertical Timeline failed:\n{traceback.format_exc()}')
    return catcher

def add_handler(event, base_class, notify_callback):
    handler_name = base_class.__name__ + 'Handler'
    handler_class = type(handler_name, (base_class,),
                         { "notify": error_catcher_wrapper(notify_callback) })
    handler_class.__init__ = lambda self: super(handler_class, self).__init__()
    handler = handler_class()
    # Avoid garbage collection
    handlers.append((handler, event))
    event.add(handler)

def run(context):
    global ui, app, handlers
    debug = False
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

         # Add a command that displays the panel.
        showPaletteCmdDef = ui.commandDefinitions.itemById('thomasa88_showVerticalTimeline')

        if not showPaletteCmdDef:
            showPaletteCmdDef = ui.commandDefinitions.addButtonDefinition(
                'thomasa88_showVerticalTimeline',
                'Show Vertical Timeline',
                'Vertical Timeline\n\n' +
                'A vertical timeline, that shows feature names. Timeline functionality is limited.',
                '')

            add_handler(showPaletteCmdDef.commandCreated,
                        adsk.core.CommandCreatedEventHandler,
                        show_palette_command_created_handler)
        
        # Add the command to the toolbar.
        panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        cntrl = panel.controls.itemById('thomasa88_showVerticalTimeline')
        if not cntrl:
            panel.controls.addCommand(showPaletteCmdDef)
        
        add_handler(ui.commandTerminated,
                    adsk.core.ApplicationCommandEventHandler,
                    command_terminated_handler)

        # Fusion bug: Activated is not called when switching to/from Drawing.
        # https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
        add_handler(app.documentActivated,
                    adsk.core.DocumentEventHandler,
                    document_activated_handler)

        add_handler(ui.workspacePreDeactivate,
                    adsk.core.WorkspaceEventHandler,
                    workspace_pre_deactivate_handler)

        add_handler(ui.workspaceActivated,
                    adsk.core.WorkspaceEventHandler,
                    workspace_activated_handler)

        print("Running")
    except:
        print('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))
        if ui and not debug:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    try:
        print('Stopping')

        for handler, event in handlers:
            event.remove(handler)
        handlers.clear()

        # Delete the palette created by this add-in.
        palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
        if palette:
            palette.deleteMe()

        # Delete controls and associated command definitions created by this add-ins
        panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        cmd = panel.controls.itemById('thomasa88_showVerticalTimeline')
        if cmd:
            cmd.deleteMe()
        cmdDef = ui.commandDefinitions.itemById('thomasa88_showVerticalTimeline')
        if cmdDef:
            cmdDef.deleteMe()
    except:
        if ui:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))


class ShowPaletteCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            global enabled
            enabled = True
            if ui.activeWorkspace.id == 'FusionSolidEnvironment':
                show_palette()
            else:
                ui.messageBox('Vertical Timeline cannot be shown in this workspace. ' +
                              'It will be shown when you open a Design.')
        except:
            ui.messageBox('Command executed Vertical Timeline failed: {}'.format(traceback.format_exc()))

def show_palette():
    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
    if not palette:
        palette = ui.palettes.add('thomasa88_verticalTimelinePalette', 'Vertical Timeline', 'palette.html',
                                    True, True, True, 250, 500, False)
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateLeft

        onHTMLEvent = HTMLEventHandler()
        palette.incomingFromHTML.add(onHTMLEvent)   
        handlers.append((onHTMLEvent, palette.incomingFromHTML))

        onClosed = CloseEventHandler()
        palette.closed.add(onClosed)
        handlers.append((onClosed, palette.closed))
    else:
        invalidate()
        if not palette.isVisible:
            palette.isVisible = True

def hide_palette():
    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
    if palette:
        palette.isVisible = False

# Event handler for the commandCreated event.
def show_palette_command_created_handler(args):
        command = args.command
        onExecute = ShowPaletteCommandExecuteHandler()
        command.execute.add(onExecute)
        handlers.append((onExecute, command.execute))
        enabled = True

# Event handler for the palette close event.
class CloseEventHandler(adsk.core.UserInterfaceGeneralEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            global enabled
            enabled = False
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))

# Event handler for the palette HTML event.                
class HTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            htmlArgs = adsk.core.HTMLEventArgs.cast(args)
            action = htmlArgs.action
            data = json.loads(htmlArgs.data)
            html_commands = []
            if action == 'ready':
                print('HTML ready')

                # Cannot do sendInfoToHTML inside the event handler. We either have to use htmlArgs.returnData or
                # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
                html_commands.append(invalidate(send=False))
            elif action == 'setFeatureName':
                item = get_item_by_id_string(data['id'].split('-'))
                ret = True
                if data['value'] == '':
                    ret = False
                elif (not item.isGroup
                    and item.entity.classType() == 'adsk::fusion::Occurrence'
                    and get_occurrence_type(item) != OCCURRENCE_BODIES_COMP):
                    item.entity.component.name = data['value']
                    html_commands.append(invalidate(send=False))
                else:
                    item.name = data['value']
                html_commands.append(ret)
            elif action == 'selectFeature':
                ret = True
                item = get_item_by_id_string(data['id'].split('-'))

                if item.isSuppressed:
                    ui.messageBox('Cannot select suppressed features')
                    ret = False
                elif item.isRolledBack:
                    ui.messageBox('Cannot select rolled back features')
                    ret = False
                else:
                    # Making this in a transactory way so the current selection is not removed
                    # if the entity is not selectable.
                    newSelection = adsk.core.ObjectCollection.create()
                    newSelection.add(item.entity)
                    try:
                        ui.activeSelections.all = newSelection
                    except:
                        ui.messageBox('Cannot select this entity')
                        ret = False
                html_commands.append(ret)
            if html_commands:
                htmlArgs.returnData = json.dumps(html_commands)
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))   

class CommandTerminationReason:
    UnknownTerminationReason = 0
    CompletedTerminationReason = 1
    CancelledTerminationReason = 2
    AbortedTerminationReason = 3
    PreEmptedTerminationReason = 4
    SessionEndingTerminationReason = 5


def command_terminated_handler(args):
    eventArgs = adsk.core.ApplicationCommandEventArgs.cast(args)

    # As long as we don't update on command create, we only need to listen for command completion
    if eventArgs.terminationReason != CommandTerminationReason.CompletedTerminationReason:
        return

    # Heavy traffic commands
    if eventArgs.commandId in ['SelectCommand', 'CommitCommand']:
        return
    
    invalidate()

#########################################################################################
# app.product is not ready at workspaceActivated, but documentActivated does not fire
# when switching to/from Drawing. However, in that case, it seems that the product is
# ready when we call get_timeline (presumably since the panel has to be recreated)
# Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
#
# PLM360OpenAttachmentCommand + MarkDocumentsForOpenCommand could possibly be used as
# another workaround.
#
# Event order:
# DocumentActivating
# OnWorkspaceActivated
# DocumentActivated
# PLM360OpenAttachmentCommand or MarkDocumentsForOpenCommand
#

def workspace_pre_deactivate_handler(args):
    #eventArgs = adsk.core.DocumentEventArgs.cast(args)
    if enabled:
        invalidate(emptyTimeline=True)

def workspace_activated_handler(args):
    #eventArgs = adsk.core.WorkspaceEventArgs.cast(args)

    if ui.activeWorkspace.id == 'FusionSolidEnvironment':
        if enabled:
            show_palette()
    else:
        # Deactivate
        hide_palette()

def document_activated_handler(args):
    #eventArgs = adsk.core.DocumentEventArgs.cast(args)
    if ui.activeWorkspace.id == 'FusionSolidEnvironment':
        if enabled:
            show_palette()

#########################################################################################