myscada=require('./myscada');
myscada.init();


//process data sent from the view script
//in view script, please, use function myscada.sendDataToServerSideScript
myscada.dataFromViewScripts = function (data,callback)
{
	//process data

	//return value back to view script
	//you must always return a value even empty
	callback("return value");
};
