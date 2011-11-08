<%doc>
USING ARRAYS OF INDICIES INSTEAD OF COPPYING DATA
 Templating variables in use:
 sub_n: The size b(n) of data to be subsampled
 n_data: The initial data size
 n_subsamples: The number of subsamples to take
 n_bootstraps: The number of bootstraps to compute per subsample
 subsmaple_threshold: the probability parameter for the subsample rng
 seq_type: The python type of the data sequence, should be list or ndarray
</%doc>


void bootstrap( const unsigned int* in, unsigned int* out ){
    <%
        if bootstrap_unroll is UNDEFINED:
	    b = 1
	else:
	    b = bootstrap_unroll
    %>
  for( int i=0; i< ${sub_n/b}; i++ ){
    % for i in range(b):
    out[i*${b} + ${i}] = in[ rand() % ${sub_n} ];
    % endfor
  }
  % for i in range(sub_n % b):
  out[${sub_n-1-i}] = in[ rand() % ${sub_n} ];
  % endfor 
}

// char subsampled[ ${n_data} ];
 void subsample( unsigned int* out ){
 //  printf("About to subsample");
  int size_out = ${sub_n};
  while( size_out > 0 ){
    unsigned int index = rand() % ${n_data};
    //if( subsampled[index] ){
      // Rely on not randomly selecting the same index
      // three times in one run
     // subsampled[index] = 0;
    //} else {
      //subsampled[index] = 1;
      out[ ${sub_n} - size_out ] = index;
      size_out--;
    //}
  }
//  for( int i=0; i<${sub_n}; i++ ){
//       subsampled[ out[i] ] = 0;
//  }
 }

void loaded_bootstrap( unsigned int * out, unsigned int* seed_cell ){
	for( int i = 0; i< ${sub_n}; i++ ){
	    out[i] = rand_r(seed_cell) % ${sub_n}; 
	}
}

void subsample_and_load( float* data, float* out, unsigned int* cell ){
%if parallel_loop is UNDEFINED or parallel_loop == 'inner':
  cilk_for( int i = 0; i<${sub_n}; i++ ){
    unsigned int tid = __cilkrts_get_worker_number();
    out[i] = data[ rand_r(cell+tid) % ${n_data} ];

  }
%else:
    int size_out = 0;
    while( size_out < ${sub_n} ){
	out[size_out] = data[ rand_r(cell) % ${n_data} ];
	size_out++;
    } 
%endif
}

void blb_chunk( float* data, float* subsample_values, float* bootstrap_estimates, unsigned int* bootstrap_indicies, float* subsample_estimates , int start, int end ){
	unsigned int cell = 0;
	for(int i = start; i < end; i++ ){
	    subsample_and_load( data, subsample_values, &cell );
	    for( int j = 0; j<${n_bootstraps}; j++ ){
		loaded_bootstrap( bootstrap_indicies, &cell);
		bootstrap_estimates[j] = compute_estimate( subsample_values, bootstrap_indicies, ${sub_n} );
	    }
	    subsample_estimates[i] = reduce_bootstraps( bootstrap_estimates, ${n_bootstraps} );
	}
}
<%doc>
float single_bootstrap( float* data, unsigned int* si, unsigned int* bi ){
      bootstrap(si, bi);
      return compute_estimate( data, bi, ${sub_n} );
}

float single_subsample( float * data, unsigned int* si, unsigned int* bi, float* be ){
	subsample(si);
	for(int j = 0; j<${n_bootstraps}; j++){
		bootstrap(si, bi);
		be[j] = compute_estimate( data, bi, ${sub_n} );
	}
	return reduce_bootstraps( be, ${n_bootstraps} );
}
</%doc>


## list is the default type.
%if seq_type == 'list': 

PyObject* compute_blb( PyObject*  data ){
  Py_INCREF(data);
  PyObject * py_arr = PyArray_FROM_OTF( data, NPY_FLOAT32, NPY_IN_ARRAY );
  Py_INCREF( py_arr );
  float * c_arr = (float*) PyArray_DATA( py_arr );

%elif seq_type == 'ndarray':

PyObject* compute_blb( PyObject* data ){
  Py_INCREF( data );
  float * c_arr = (float*) PyArray_DATA( data );

%endif
  //printf("About to begin\n");
  //memset( subsampled, 0, ${n_data} );

  //note that these are never cleared; We always fill them up
  //with the appropriate data before perform calculations on them.
  float * subsample_estimates = (float*) calloc( ${n_subsamples}, sizeof(float) );
  float * subsample_values = (float*) calloc( ${sub_n*(cilk_n_workers+1)}, sizeof(unsigned int) );    
  unsigned int * bootstrap_indicies = (unsigned int*) calloc( ${sub_n*(1+cilk_n_workers)}, sizeof(unsigned int) );
  float * bootstrap_estimates =  (float*) calloc( ${n_bootstraps*(cilk_n_workers+1)}, sizeof(float) );
  unsigned int* cells = (unsigned int*) calloc( ${cilk_n_workers+1}, sizeof(unsigned int) );
  

  __cilkrts_set_param("nworkers","${cilk_n_workers}");

  %if parallel_loop is UNDEFINED or parallel_loop == 'inner':
  for( int i = 0; i<${n_subsamples}; i++ ){
	subsample_and_load( c_arr, subsample_values, cells );
	cilk_for( int j = 0; j<${n_bootstraps}; j++ ){
	    unsigned int tid = __cilkrts_get_worker_number();
	    unsigned int * local_indicies = bootstrap_indicies+(tid*${sub_n});
	    loaded_bootstrap( local_indicies, cells+tid );
	    bootstrap_estimates[j] = compute_estimate( subsample_values, local_indicies, ${sub_n} );
	}
	subsample_estimates[i] = reduce_bootstraps( bootstrap_estimates, ${n_bootstraps} );
   }
 %elif parallel_loop == 'outer':	    
  cilk_for(int i =0; i<${n_subsamples}; i++ ){
        unsigned int tid = __cilkrts_get_worker_number();
	float * local_values = subsample_values+(tid*${sub_n});
    	subsample_and_load(c_arr, local_values, cells+tid );
	float * local_estimates = bootstrap_estimates+(tid*${n_bootstraps});
    	for(int j = 0; j<${n_bootstraps}; j++ ){

	   unsigned int* local_indicies = bootstrap_indicies+(tid*${sub_n});
	   loaded_bootstrap( local_indicies, cells+tid );
           local_estimates[j] = compute_estimate( local_values, local_indicies, ${sub_n} );
        }
	subsample_estimates[i] = reduce_bootstraps(local_estimates, ${n_bootstraps});
   }
  %elif parallel_loop == 'manual':
    int step = ${n_subsamples/cilk_n_workers};
    int rem = ${n_subsamples % cilk_n_workers};	
#pragma cilk grainsize = 1
    cilk_for( int i = 0; i<${cilk_n_workers}; i++ ){
	int end = i ? i+step : rem+step;
	blb_chunk( c_arr, subsample_values+(i*${sub_n}), bootstrap_estimates+(i*${n_bootstraps}),
				bootstrap_indicies+(i*${sub_n}), subsample_estimates, i, end );
    }
    cilk_sync; 
  %endif

  free( cells ); 
  float theta = average( subsample_estimates, ${n_subsamples} );
  free( subsample_estimates );
  free( bootstrap_indicies );
  free( bootstrap_estimates );
  free( subsample_values );

%if seq_type is UNDEFINED or seq_type == 'list':
  Py_DECREF( py_arr );
%endif
  Py_DECREF( data );
  unsigned int dealloc_time = time(NULL);
  return PyFloat_FromDouble(theta);
}