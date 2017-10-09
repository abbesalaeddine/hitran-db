from aenum import Enum
from hapi import *
from threading import Thread

# An enum for all possible errors that could be encountered while verifying fetch parameters
# and while actually fetching the data
class FetchErrorKind(Enum):
    BadParameter = 1            # This wont be used
    BadParameterGroup = 2       # This wont be used
    BadNuMin = 3                # This wont be used
    BadNuMax = 4                # This wont be used
    BadConnection = 5
    BadIsoList = 6
    FailedToRetreiveData = 7
    FailedToOpenThread = 8

# A class that contains a FetchErrorKind along with a description for the error
class FetchError(object):

    # Constructor for FetchError
    #
    # errors: a FetchErrorKind object
    # description: a textual description of the error
    def __init__(self, error, description = ''):
        self.error = error
        self.description = description

class DataHandle(object):
    def __init__(self, data_name):
        self.data_name = data_name


    # A safer handle to the try_fetch function that provides feedback on parameters
    # if they're invalid.
    #
    # RETURNS:
    # True if the fetch went through successfully
    #
    # iso_id_list:      the list of all of the global id's of the isotopologues
    #                   that data should be fetched on.
    # numin:            minimum wavenumber
    # numax:            maximum wavenumber
    # parameter_groups: any aditional groups of parameters to include in the fetch
    # parameters        any additional individual parameters to include in the fetch
    def try_fetch(self, fetch_window, iso_id_list, numin, numax, parameter_groups = [], parameters = []):
        # A list to add errors to if there are any
        errors = []


        if len(iso_id_list) == 0:
            errors.append(FetchError(FetchErrorKind.BadIsoList, 'Bad isotopologue list: you must select at least one isotopologue'))

        # If the len isn't zero there was an error
        if len(errors) != 0:
            return errors

        def send_request():
            fetch_window.gui.fetch_button.setDisabled(True)
            # Try to send the fetch request, if there is an issue, it is going to be
            # related to internet connection.
            try:
                # Call the hapi fetch method
                fetch_by_ids(self.data_name, iso_id_list, numin, numax, parameter_groups, parameters)
            except Exception as e:
                as_str = str(e)
                err_(as_str)
                # Determine whether the issue is an internet issue or something else
                if 'connect' in as_str:
                    fetch_window.fetch_error(FetchError(
                                FetchErrorKind.BadConnection,
                                'Bad connection: Failed to connect to send request. Check your connection.'))
                fetch_window.fetch_error(FetchError(
                                FetchErrorKind.FailedToRetreiveData,
                                'Fetch failure: Failed to fetch data (connected successfully, received HTTP error as response)'))

            # whether there is an error or not, set the button back to enabled
            finally:
                fetch_window.gui.fetch_button.setEnabled(True)

        # Open a new thread to prevent the GUI from freezing while the data is being fetched.
        try:
            Thread(target = send_request, args=()).start()
        except Exception as e:
            return [FetchError(
                        FetchErrorKind.FailedToOpenThread,
                        'Thread failure: Failed to open thread tp call fetch')]

        return True
