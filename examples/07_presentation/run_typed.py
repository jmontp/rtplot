"""Typed equivalent of the presentation demo; same application loop."""
import run as demo
from rtplot.client import Button, ControlsRow, Plot, PlotRow, Section, Slider, Text, TextInput, View


def configuration():
    return [
        ControlsRow([Text('hardware','Hardware','Simulated · ready',appearance='state'),
                     Button('stop','Stop',appearance='danger')],section='status'),
        ControlsRow([Text('help','','Prepare the synthetic source before starting. No hardware is connected.',appearance='help'),
                     Button('prepare','Prepare',appearance='primary'), Button('start','Start',appearance='primary'),
                     TextInput('note','Notes','Keep this edit while resizing')],section='setup',title='Preparation'),
        PlotRow([Plot(names=['Signal','Reference'],title='Tracking',xrange=120,min_height=220,
                      colors=['#175fa5','#a53c00'],line_style=['solid','dashed']),
                 Plot(names=['Error'],title='Error',xrange=120,min_height=220,colors=['#923d88']),
                 Plot(names=['Detail'],title='Detail',xrange=120,min_height=220,colors=['#087563'],line_style=['dotted'])],
                columns=3,section='work'),
        ControlsRow([Button('raw','Raw',appearance='choice'),Button('smooth','Smoothed',appearance='choice')],
                    section='advanced',title='Source choice',exclusive=True),
        ControlsRow([Slider('gain','Gain',0,2,value=1),Button('reset','Reset settings',appearance='warning'),
                     Text('advanced_help','','These controls change the example only. Expand sections and resize without resetting the stream.',appearance='help')],
                    section='advanced',title='Optional settings'),
    ], View([Section('status','Status',density='compact',show_heading=False),Section('setup','Setup'),
             Section('work','Work'),Section('advanced','Advanced',navigation='secondary',collapsible=True,collapsed=True)],
            persistent_section='status',essential_controls=['hardware','stop'])


if __name__ == '__main__':
    demo.main(configuration)
