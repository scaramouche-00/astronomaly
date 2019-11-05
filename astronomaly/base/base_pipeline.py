from astronomaly.base import logging_tools
from os import path
import pandas as pd
import numpy as np
from pandas.util import hash_pandas_object
import time


class PipelineStage(object):
    def __init__(self, *args, **kwargs):
        """
        Base class defining functionality for all pipeline stages. To contribute a new pipeline stage to Astronomaly,
        create a new class and inherit PipelineStage. Always start by calling "super().__init__()" and pass it all the
        arguments of the init function in your new class. The only other function that needs to be changed is
        `_execute_function` which should actually implement pipeline stage functionality. The base class will take care
        of automatic logging, deciding whether or not a function has already been run on this data, saving and loading
        of files and error checking of inputs and outputs.

        Parameters
        ----------
        force_rerun : bool
            If True will force the function to run over all data, even if it has been called before.
        save_output : bool
            If False will not save and load any files. Only use this if functions are very fast to rerun or if you
            cannot write to disk.
        output_dir : string
            Output directory where all outputs will be stored. Defaults to current working directory.
        file_format : string
            Format to save the output of this pipeline stage to. Accepted values are:
            parquet

        """
        # This will be the name of the child class, not the parent.
        self.class_name = type(locals()['self']).__name__
        self.function_call_signature = logging_tools.format_function_call(self.class_name, *args, **kwargs)

        # Disables the automatic saving of intermediate outputs
        if 'save_output' in kwargs and kwargs['save_output'] is False:
            self.save_output = False
        else:
            self.save_output = True

        # Handles automatic file reading and writing
        if 'output_dir' in kwargs:
            self.output_dir = kwargs['output_dir']
        else:
            self.output_dir = './'

        # This allows the automatic logging every time this class is instantiated (i.e. every time this pipeline stage
        # is run). That means any class that inherits from this base class will have automated logging.

        logging_tools.setup_logger(path.join(self.output_dir, 'astronomaly.log'))

        if 'force_rerun' in kwargs and kwargs['force_rerun']:
            self.args_same = False
            self.checksum = ''
        else:
            self.args_same, self.checksum = logging_tools.check_if_inputs_same(self.class_name, locals()['kwargs'])

        if 'file_format' in kwargs:
            self.file_format = kwargs['file_format']
        else:
            self.file_format = 'parquet'

        self.output_file = path.join(self.output_dir, self.class_name + '_output')
        if self.file_format == 'parquet':
            if '.parquet' not in self.output_file:
                self.output_file += '.parquet'

        if path.exists(self.output_file) and self.args_same:
            self.previous_output = self.load(self.output_file)
        else:
            self.previous_output = pd.DataFrame(data=[])

        self.labels = []

    def save(self, output, filename):
        if self.save_output:
            if self.file_format == 'parquet':
                if '.parquet' not in filename:
                    filename += '.parquet'
                # Parquet needs strings as column names (which is good practice anyway)
                output.columns = output.columns.astype('str')
                output.to_parquet(filename)

    def load(self, filename):
        if self.file_format == 'parquet':
            if '.parquet' not in filename:
                filename += '.parquet'
            output = pd.read_parquet(filename)
        return output

    def hash_data(self, data):
        """
        Returns a checksum on the first few rows of a DataFrame to allow checking if the input changed.

        Parameters
        ----------
        data : pd.DataFrame or similar
            The input data on which to compute the checksum

        Returns
        -------
        checksum : str
            The checksum
        """
        hash_per_row = hash_pandas_object(data)
        return int(hash_pandas_object(pd.DataFrame([hash_per_row.values])).values[0])

    def run(self, data):
        # This has logic to decide whether to run the function and how to chop up the data
        new_checksum = self.hash_data(data)
        if self.args_same and new_checksum == self.checksum:
            # This means we've already run this function for all instances in the input and with the same arguments
            msg = """Pipeline stage %s previously called with same arguments and same data. Loading from file.
                    Use 'force_rerun=True' in init args to override this behavior.""" % self.class_name
            logging_tools.log(msg, level='WARNING')
            return self.previous_output
        else:
            msg_string = self.function_call_signature + ' - checksum: ' + (str)(new_checksum)
            # print(msg_string)
            logging_tools.log(msg_string)
            print('Running', self.class_name, '...')
            t1 = time.time()
            output = self._execute_function(data)
            self.save(output, self.output_file)
            print('Done! Time taken:', (time.time() - t1), 's')
            return output

    def run_on_dataset(self, dataset=None):
        # ***** The idea is to be able to run this on new data but this will be buggy. Need another look at this before
        # running it new data ******
        if not self.args_same:
            # If the arguments have changed we rerun everything
            msg_string = self.function_call_signature
            logging_tools.log(msg_string)
        else:
            # Otherwise we only run instances not already in the output
            msg = """Pipeline stage %s previously called with same arguments. Loading from file. Will only run for new samples.
                    Use 'force_rerun=True' in init args to override this behavior.""" % self.class_name
            logging_tools.log(msg, level='WARNING')

        print('Extracting features using', self.class_name, '...')
        t1 = time.time()

        new_index = []
        output = []
        n = 0
        for i in dataset.index:
            if i not in self.previous_output.index or not self.args_same:
                if n % 100 == 0:
                    print(n, 'instances completed')
                input_instance = dataset.get_sample(i)
                out = self._execute_function(input_instance)
                if len(output) == 0:
                    output = np.empty([len(dataset.index), len(out)])
                output[n] = out
                new_index.append(i)
            n += 1

        new_output = pd.DataFrame(data=output, index=new_index, columns=self.labels)

        if self.args_same and not new_output.index.equals(self.previous_output.index):
            output = pd.concat((self.previous_output, new_output))
        else:
            output = new_output

        if self.save_output:
            self.save(output, self.output_file)
        print('Done! Time taken: ', (time.time() - t1), 's')

        return output

    def _execute_function(self, data):
        # This does the actual work
        raise NotImplementedError
