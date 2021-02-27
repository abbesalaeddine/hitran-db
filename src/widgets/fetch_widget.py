from PyQt5 import QtGui, uic
from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import hapi
from metadata.parameter_availability import ParameterAvailability
from metadata.isotopologue_meta import IsotopologueMeta
from metadata.molecule_meta import MoleculeMeta
from utils.fetch_error import FetchErrorKind
from utils.hapiest_util import get_all_data_names
from widgets.select_widget import SelectWidget
from widgets.view_widget import ViewWidget
from worker.hapi_worker import *


class FetchWidget(QWidget):
    FETCH_WIDGET_INSTANCE = None

    def __init__(self, parent):
        QWidget.__init__(self)

        if FetchWidget.FETCH_WIDGET_INSTANCE is not None:
            raise Exception("No more than one instance of FetchWidget should be created.")
        FetchWidget.FETCH_WIDGET_INSTANCE = self

        self.parent = parent

        self.children = []
        self.parameter_group_items = {}
        self.parameter_items = {}

        self.data_name: QLineEdit = None
        self.fetch_button: QPushButton = None
        self.clear_param_button: QPushButton = None
        self.list_container: QWidget = None
        self.molecule_id: QComboBox = None
        self.numax: QDoubleSpinBox = None
        self.numin: QDoubleSpinBox = None
        self.iso_list: QListWidget = None
        self.param_group_list: QListWidget = None
        self.param_list = None
        self.select_button: QPushButton = None
        self.edit_button: QPushButton = None
        self.completer = None  # Gets initialized in populate_molecule_list

        uic.loadUi('layouts/fetch_widget.ui', self)

        self.init_molecule_list()
        self.init_parameter_lists()

        # Sets up auto-complete for molecule names
        self.molecule_id.setEditable(True)
        aliases = MoleculeMeta.all_aliases_with_line_by_line_data()
        self.completer = QCompleter(aliases, self)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.molecule_id.setCompleter(self.completer)

        # A regular expression that all valid data-names match (strips out characters that arent
        # safe
        # for paths in windows / unix operating systems)
        re = QtCore.QRegExp('[^<>?\\\\/*\x00-\x1F]*')
        validator = QtGui.QRegExpValidator(re)
        self.data_name.setValidator(validator)

        self.iso_list.itemPressed.connect(self.__iso_list_item_click)
        self.fetch_button.clicked.connect(self.__handle_fetch_clicked)
        self.numax.valueChanged.connect(self.__numax_change)
        self.numin.valueChanged.connect(self.__numin_change)
        self.edit_button.clicked.connect(self.__on_edit_clicked)
        self.select_button.clicked.connect(self.__on_select_clicked)
        self.clear_param_button.clicked.connect(self.__on_clear_clicked)

        # Calling this will populate the isotopologue list with isotopologues of
        # whatever the default selected molecule is. This has to be called after
        # the drop-down list is populated so there is something to be selected
        self.__molecule_id_text_changed()

        # Set the molecule_id change method to the one we defined in the class
        self.molecule_id.currentIndexChanged.connect(self.__molecule_id_text_changed)

        # QToolTip.setFont(QFont('SansSerif', 10))
        self.param_group_list.setToolTip('Specifies "non-standard" parameter to query.')
        self.param_list.setToolTip('Specifies parameters to query.')
        self.iso_list.setToolTip('Select the molecule isotopologues you wish to query.')
        self.molecule_id.setToolTip('Type in, or use the drop-down menu to select your molecule.')
        self.data_name.setToolTip('Specify local name for fetched data')
        self.numin.setToolTip(
            'Specify lower bound wave number to query, must be positive number.\n(default: '
            'absolute min for given molecule).')
        self.numax.setToolTip(
            'Specify upper bound wave number to query, must be greater than min wave number.\n('
            'default: absolute max for given molecule)')
        self.fetch_button.setToolTip('Fetch data from HITRAN!')

    def init_parameter_lists(self):
        self.param_group_list.itemClicked.connect(self.__on_group_clicked)
        for group in hapi.PARAMETER_GROUPS:
            item = QtWidgets.QListWidgetItem(group)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)

            item.setCheckState(QtCore.Qt.Unchecked)

            self.param_group_list.addItem(item)
            self.parameter_group_items[group] = item

        for par in hapi.PARLIST_ALL:
            item = QtWidgets.QListWidgetItem(par)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)

            item.setCheckState(QtCore.Qt.Unchecked)

            self.param_list.addItem(item)
            self.parameter_items[par] = item

    def init_molecule_list(self):
        """
        Extract the name of each molocule that hapi has data on and add it to the molecule list.
        Also, enable auto-complete for the combobox.
        """
        # our list of molecule names in the gui
        molecules = []

        for molecule_id in range(0, 100):
            try:
                molecule = MoleculeMeta(molecule_id)
                iso = IsotopologueMeta(molecule_id, 1)
                if not molecule.is_populated():
                    continue
                molecules.append(molecule)
            except Exception as e:
                continue

        # Ensure they are sorted by hitran id. They were before this line, but that was sort of just
        # a coincidence
        molecules = sorted(molecules, key=lambda m: m.id)

        list(map(lambda mol: self.molecule_id.addItem(mol.name), molecules))

    def populate_parameter_lists(self):
        """
        Populates the parameter lists with all parameters from a specific group.
        """
        ba = ParameterAvailability(self.molecule_id.currentText())
        print(ba)
        if not ba.molecule.populated:
            return

        self.param_group_list.clear()
        self.param_list.clear()

        self.parameter_items = {}
        self.parameter_group_items = {}

        # TODO: Fix parameter availability so the filtered groups can be used rather than all
        # for group in sorted(list(ba.parameter_groups()), key=str.lower):
        for group in sorted(list(hapi.PARAMETER_GROUPS.keys()), key=str.lower):
            item = QtWidgets.QListWidgetItem(group)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)

            item.setCheckState(QtCore.Qt.Unchecked)

            self.parameter_group_items[group] = item
            self.param_group_list.addItem(item)

        # TODO: Fix parameter availability so the filtered parameters can be used rather than all
        for par in sorted(list(hapi.PARLIST_ALL), key=str.lower):
            item = QtWidgets.QListWidgetItem(par)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)

            item.setCheckState(QtCore.Qt.Unchecked)

            self.parameter_items[par] = item
            self.param_list.addItem(item)

    def fetch_done(self, work_result: WorkResult):
        """
        User feedback for GUI paramter fields of the fetch function in the Main Window.

        :param work_result contains the work result (error or success)
        """
        try:
            self.parent.remove_worker_by_jid(work_result.job_id)
            result = work_result.result
            self.enable_fetch_button()
            if result is not None and 'all_tables' in result:
                log("Successfully finished fetch.")
                self.parent.populate_table_lists(result['all_tables'])
                return
            err_log("Failed to fetch...")
            if isinstance(result, List):
                errs = result
            else:
                errs = [result]
            for err in errs:
                # This means the wavenumber range was too small (probably), so
                # we'll tell the user it is too small
                if err.error == FetchErrorKind.FailedToRetrieveData:
                    err_log('The entered wavenumber range is too small, try increasing it')
                # Not much to do in regards to user feedback in this case....
                elif err.error == FetchErrorKind.FailedToOpenThread:
                    err_log('Failed to open thread to make query HITRAN')
                elif err.error == FetchErrorKind.BadConnection:
                    err_log('Error: Failed to connect to HITRAN. Check your internet connection '
                            'and try again.')
                elif err.error == FetchErrorKind.BadIsoList:
                    err_log(' Error: You must select at least one isotopologue.')
                elif err.error == FetchErrorKind.EmptyName:
                    pass

        except Exception as e:
            debug(e)

    def disable_fetch_button(self):
        """
        Disable fetch button to disallow user to stack data requests.

        """
        self.fetch_button.setDisabled(True)

    def enable_fetch_button(self):
        """
        Re-enables fetch button to allow user to request data.

        """
        self.fetch_button.setEnabled(True)

    ###
    # Event Handlers
    ###

    def __on_group_clicked(self, i: QListWidgetItem):
        """
        Enables clicking the 'all' list item to toggle all other items
        in the parameter group list
        """
        group_name = i.text()

        if group_name not in hapi.PARAMETER_GROUPS:
            return

        if group_name == "all":
            check_state = self.parameter_group_items[group_name].checkState()
            for group in self.parameter_group_items:
                if group == "all":
                    continue
                self.parameter_group_items[group].setCheckState(check_state)

            for param in self.parameter_items:
                self.parameter_items[param].setCheckState(check_state)

        for param in hapi.PARLIST_ALL:
            if param not in self.parameter_items:
                continue
            self.parameter_items[param].setCheckState(QtCore.Qt.Unchecked)

        for group in hapi.PARAMETER_GROUPS:
            if group not in self.parameter_group_items:
                continue

            item = self.parameter_group_items[group]
            if item.checkState() == QtCore.Qt.Checked:
                for param in hapi.PARAMETER_GROUPS[group]:
                    if param not in self.parameter_items:
                        continue
                    self.parameter_items[param].setCheckState(QtCore.Qt.Checked)

    def __on_clear_clicked(self):
        for item in self.param_group_list.findItems("*", QtCore.Qt.MatchWildcard):
            item.setCheckState(QtCore.Qt.Unchecked)
        for item in self.param_list.findItems("*", QtCore.Qt.MatchWildcard):
            item.setCheckState(QtCore.Qt.Unchecked)

    def __iso_list_item_click(self, item):
        """
        Toggle the item that was activated.
        """
        if item.checkState() == QtCore.Qt.Checked:
            item.setCheckState(QtCore.Qt.Unchecked)
        else:
            item.setCheckState(QtCore.Qt.Checked)

    def __numax_change(self, value):
        """
        when the numax spinbox changes, make sure it's value isn't lower than that of numin,
        and ensure the value isn't
        greater than the maximum.
        """
        max = self.numax.maximum()
        if value > max:
            self.numin.setValue(max)
            return

    def __numin_change(self, value):
        """
        when the numin spinbox changes make sure it's value isn't greater than that of numax,
        and make sure it's value
        isn't below the minimum.
        """
        min = self.numin.minimum()
        if value < min:
            self.numin.setValue(min)

    def __molecule_id_text_changed(self):
        """
        This method repopulates the isotopologue list widget after the molecule
        that is being worked with changes.
        """
        molecule = self.get_selected_molecule()
        if not molecule.is_populated():
            return

        self.populate_parameter_lists()
        self.data_name.setText(str(molecule.name).lower().replace(' ', '_').strip())

        molecule = IsotopologueMeta(molecule.id, 1)

        # Get the range
        min, max = molecule.get_wn_range()

        # Change the range for wn
        self.numin.setMinimum(min)
        self.numax.setMaximum(max)

        self.numin.setValue(min)
        self.numax.setValue(max)

        # Remove all old elements
        self.iso_list.clear()

        # For each isotopologue this molecule has..
        for isotopologue in molecule.get_all_isos():

            # Create a new item, ensure it is enabled and can be checked.
            item = QtWidgets.QListWidgetItem()

            # Create a label to allow the rendering of rich text (fancy molecular formulas)
            label = QtWidgets.QLabel(isotopologue.html)

            # Allow the use of html formatted text
            label.setTextFormat(QtCore.Qt.RichText)

            # Make sure there is a key associated with the item so we can use it later
            item.setData(QtCore.Qt.UserRole, isotopologue.id)
            item.setFlags(
                item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled |
                QtCore.Qt.ItemIsSelectable)

            # The normal molecule is always at index 1, and we always want that
            # molecule to be selected
            if isotopologue.iso_id != 1:
                item.setCheckState(QtCore.Qt.Unchecked)
            else:
                item.setCheckState(QtCore.Qt.Checked)

            self.iso_list.addItem(item)
            self.iso_list.setItemWidget(item, label)

    def __handle_fetch_clicked(self):
        """
        Handles fetching of data, checks to make sure that certain things are proper such as min
        values being smaller than max numbers.
        """
        self.disable_fetch_button()

        numax = self.get_numax()
        numin = self.get_numin()

        if numax < numin:
            self.numax.setValue(numin)
            self.numin.setValue(numax)
            temp = numin
            numin = numax
            numax = temp

        parameter_groups = self.get_selected_param_groups()
        parameters = self.get_selected_params()
        log(str("Sending fetch request..."))

        selected_isos = self.get_selected_isotopologues()
        if len(selected_isos) == 0:
            return

        self.disable_fetch_button()
        work = HapiWorker.echo(data_name=self.get_data_name(), iso_id_list=selected_isos,
                               numin=numin, numax=numax, parameter_groups=parameter_groups, parameters=parameters)
        self.worker = HapiWorker(WorkRequest.FETCH, work, callback=self.fetch_done)
        self.parent.workers.append(self.worker)
        self.worker.start()

    def eventFilter(self, object: QObject, event: QEvent):
        return False

    def __on_edit_clicked(self, *_args):
        new_edit_window = ViewWidget(self.parent)
        # new_edit_window.installEventFilter(self)
        self.children.append(new_edit_window)
        new_edit_window.show()

        ViewWidget.set_table_names(get_all_data_names())

    def __on_select_clicked(self, *_args):
        new_select_window = SelectWidget(self.parent)
        # new_select_window.installEventFilter(self)
        self.children.append(new_select_window)
        new_select_window.show()

        SelectWidget.set_table_names(get_all_data_names())

    def set_molecule_id(self, molecule_id):
        self.molecule_id.setCurrentText(molecule_id)
        self.__molecule_id_text_changed()

    def get_selected_molecule(self) -> MoleculeMeta:
        """
        converts the selected molecule to a molecule id.
        """
        return MoleculeMeta(self.molecule_id.currentText())

    def get_selected_isotopologues(self):
        """
        Returns a list containing all of the checked isotopologues.
        """
        selected_isos = []

        for i in range(self.iso_list.count()):
            # get the i'th item from the list
            item = self.iso_list.item(i)

            # Only add checked items
            if item.checkState() == QtCore.Qt.Checked:
                id = item.data(QtCore.Qt.UserRole)
                selected_isos.append(id)

        return selected_isos

    def get_selected_params(self):
        """
        Returns a list containing all of the checked parameters.
        """
        selected_params = []

        # Look at each parameter and add the checked ones to the list
        for i in range(self.param_list.count()):

            item = self.param_list.item(i)

            if item.checkState() == QtCore.Qt.Checked:
                selected_params.append(str(item.text()))

        return selected_params

    def get_selected_param_groups(self):
        """
        Returns a list containing all of the checked groups.
        """
        selected_groups = []

        # Look at each group and add the checked ones to the list
        for i in range(self.param_group_list.count()):

            item = self.param_group_list.item(i)

            if item.checkState() == QtCore.Qt.Checked:
                selected_groups.append(str(item.text()))

        return selected_groups

    def get_data_name(self):
        """
        Returns data name for fetch tab.
        """
        return str(self.data_name.text()).strip()

    def get_numax(self):
        """
        Fetches the double value from the QDoubleSpinBox numax.
        """
        return self.numax.value()

    def get_numin(self):
        """
        Fetches the double value from the QDoubleSpinBox numin.
        """
        return self.numin.value()
